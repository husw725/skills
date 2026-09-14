#!/usr/bin/env python3
"""素材前置处理 pipeline: 下载 -> 切镜头/切片 -> 台词转写 -> 镜头分析 -> 原片分镜表

产出目录结构 (output/<片名>/):
  source.mp4        原片
  scenes.json       镜头切换点 [{shot_id, start, end}]  (秒)
  clips/            物理切片 (每镜头一个 mp4)
  frames/           每镜头 2 张关键帧 (首帧+中帧, 640px jpg)
  transcript.json   带时间戳台词 [{start, end, speaker, text}]
  shots.json        每镜头视觉分析 (景别/运镜/场景/人物/动作/情绪)
  storyboard.json   合并后的完整分镜表
  storyboard.md     人类可读分镜表

断点续跑: 阶段产物存在即跳过; Gemini 调用逐块落盘到 *.partial.jsonl, 中断后重跑
同一命令从断点继续。--force 全部重跑; --force-from <stage> 只重跑某阶段及下游。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MODEL = os.environ.get("VIDEO_REDRAW_MODEL", "gemini-3.1-flash-lite")
FRAMES_PER_SHOT = 2          # ponytail: 改这里只影响分析读取, 抽帧时间点在 stage_scenes 里写死为首帧+中帧
SHOTS_PER_BATCH = 8          # 每次 Gemini 调用分析的镜头数
AUDIO_CHUNK_SEC = 600        # 音频转写分段长度
MIN_SHOT_SEC = 1.2           # 最小镜头时长, 低于此的碎片并入前镜
SPEED = 1.0                  # 录制倍速: 源片按 N 倍速录制时设 N, 时间码自动还原为真实值(main 里从 --speed 覆盖)
OVERLAYS: list[tuple[float, float]] = []   # 真实时间区间(秒), 抽帧避开: 录屏时控件入镜窗口, 来自 hg_split 的 ep_NNN.json
UPLOAD_TIMEOUT = 180         # Files API 处理超时(秒)


def sh(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def ffmpeg(*args):
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def fmt_tc(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------- Claude CLI 辅助 ----------
# 全走订阅额度: 识别层并行批量跑, 全局归并一次调用
# 识别层默认 sonnet: ep101 实测 haiku 外貌描述粒度不足, 女主 72 镜被归并层打散(27 镜混入群演),
# 主角追踪是分镜表命门, 不能再降档
RECOG_MODEL = os.environ.get("VIDEO_REDRAW_RECOG_MODEL", "sonnet")
MERGE_MODEL = os.environ.get("VIDEO_REDRAW_MERGE_MODEL", "sonnet")
PARALLEL = int(os.environ.get("VIDEO_REDRAW_PARALLEL", "4"))
# Windows 上 claude 是 .cmd/.exe, CreateProcess 不查 PATHEXT, 传裸名字会 FileNotFoundError, 必须给全路径
CLAUDE = shutil.which("claude") or "claude"


def extract_json(text: str):
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def claude_json(prompt: str, model: str, timeout: int = 900):
    """走本机 claude CLI 订阅做多模态分析, 输出 JSON; 解析失败重试后抛错。"""
    for attempt in range(3):
        # prompt 走 stdin 而非 argv: Windows 上 claude 是 .cmd, 经 cmd.exe 转发时多行 argv 会在第一个
        # 换行处截断 —— 镜头图片路径全丢, 模型收到空图片列表却照样输出散文, 解析必然失败。顺带绕开 argv 32KB 上限
        r = subprocess.run([CLAUDE, "-p", "--model", model,
                            "--allowedTools", "Read"],
                           input=prompt, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")  # 不显式指定时 Windows 按 cp936 解码, 中文全乱
        data = extract_json(r.stdout)
        if data is not None:
            return data
        print(f"  ! Claude 输出解析失败, 重试 {attempt + 1}/2")
    raise RuntimeError(f"Claude CLI 连续解析失败: {(r.stderr or r.stdout)[:200]}")


# ---------- Gemini 辅助 ----------

def gen_json(client, contents, schema):
    """结构化输出调用; parsed=None(截断/安全拦截等)时重试, 最终失败抛错而不是静默丢数据。"""
    for attempt in range(3):
        resp = client.models.generate_content(
            model=MODEL, contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": schema},
        )
        if resp.parsed is not None:
            return resp.parsed
        print(f"  ! 结构化输出解析失败, 重试 {attempt + 1}/2")
    raise RuntimeError(f"Gemini 结构化输出连续解析失败: {str(getattr(resp, 'text', ''))[:200]}")


def upload_ready(client, path: Path):
    """上传文件并等到 ACTIVE; FAILED 或超时直接抛错。"""
    f = client.files.upload(file=str(path))
    t0 = time.monotonic()
    while f.state and f.state.name == "PROCESSING":
        if time.monotonic() - t0 > UPLOAD_TIMEOUT:
            raise RuntimeError(f"Files API 处理超时: {path.name}")
        time.sleep(2)
        f = client.files.get(name=f.name)
    if f.state and f.state.name != "ACTIVE":
        raise RuntimeError(f"Files API 上传失败({f.state.name}): {path.name}")
    return f


# ---------- 逐块落盘 ----------

def load_partial(path: Path) -> dict:
    done = {}
    if path.exists():
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            done[rec["idx"]] = rec["data"]
    return done


def append_partial(path: Path, idx: int, data):
    with path.open("a") as fp:
        fp.write(json.dumps({"idx": idx, "data": data}, ensure_ascii=False) + "\n")


# ---------- 2.1 下载 ----------

def stage_download(url: str, workdir: Path) -> Path:
    out = workdir / "source.mp4"
    if not list(workdir.glob("subs*.vtt")) and not (workdir / "transcript.json").exists():
        # 先抓字幕(人工优先, 其次自动), 有字幕转写阶段就不用花 Gemini
        try:
            sh(["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
                "--sub-langs", "en.*,zh.*", "--sub-format", "vtt",
                "-o", str(workdir / "subs"), url])
        except subprocess.CalledProcessError:
            print("[下载] 字幕获取失败, 转写阶段将走 Gemini")
    def verify(p: Path):
        """续传拼接可能产生视频流残缺但合并不报错的文件, 用音视频流时长差兜底。"""
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                            "-of", "csv=p=0", str(p)], capture_output=True, text=True)
        durs = {}
        for line in r.stdout.splitlines():
            k, _, v = line.partition(",")
            try:
                durs[k] = float(v)
            except ValueError:
                pass
        if "video" in durs and "audio" in durs and durs["video"] < durs["audio"] * 0.95:
            p.unlink()
            sys.exit(f"[下载] 视频流残缺 ({durs['video']:.0f}s < 音频 {durs['audio']:.0f}s), "
                     f"已删除 {p.name}, 请重跑重新下载")

    if out.exists():
        verify(out)
        print(f"[下载] 已存在, 跳过: {out}")
        return out
    print(f"[下载] {url}")
    # 优先 H.264(avc1): AV1/VP9 本机 OpenCV 解不了; opus 等音轨无法 copy 进 mp4, 合并时统一转 AAC
    sh(["yt-dlp", "-f",
        "bv*[height<=1080][vcodec^=avc1]+ba/bv*[height<=1080]+ba/b[height<=1080]",
        "--retries", "10", "--fragment-retries", "10",  # 本地网络偶发瞬断, 别让整条 pipeline 陪葬
        "--merge-output-format", "mp4",
        "--postprocessor-args", "Merger:-c:v copy -c:a aac",
        "-o", str(out), url])
    verify(out)
    return out


# ---------- 2.2 切镜头 + 切片 + 关键帧 ----------

def pick_frame_time(t: float, lo: float, hi: float) -> float:
    """t 落在控件入镜窗口内时, 在本镜头 [lo, hi) 范围内挪到窗口外最近处(优先窗口后); 挪不开就原样返回。"""
    for a, b in OVERLAYS:
        if a <= t < b:
            for cand in (b + 0.1, a - 0.1):
                if lo <= cand < hi:
                    return cand
    return t


def stage_scenes(video: Path, workdir: Path) -> list[dict]:
    scenes_file = workdir / "scenes.json"
    if scenes_file.exists():
        print(f"[切片] 已存在, 跳过: {scenes_file}")
        return json.loads(scenes_file.read_text())

    # AdaptiveDetector 缓解运镜误切; 1.2s 地板去亚秒碎片 (ep101 A/B: 437镜 -> 387镜, <1s 归零)
    import cv2
    from scenedetect import detect, AdaptiveDetector
    from scenedetect.video_stream import VideoOpenFailure
    fps = cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FPS)
    min_len = int(MIN_SHOT_SEC * fps) if fps > 0 else 29
    print("[切片] 检测镜头切换点…")
    try:
        raw = detect(str(video), AdaptiveDetector(min_scene_len=min_len), show_progress=True)
    except VideoOpenFailure:
        # OpenCV 解不了 AV1/VP9 等编码, 转成 H.264 再试
        h264 = workdir / "source_h264.mp4"
        if not h264.exists():
            print("[切片] OpenCV 无法解码, 转码为 H.264…")
            tmp = workdir / "source_h264.tmp.mp4"
            ffmpeg("-i", str(video), "-c:v", "libx264", "-preset", "fast",
                   "-crf", "20", "-c:a", "copy", str(tmp))
            tmp.rename(h264)
        video = h264
        raw = detect(str(video), AdaptiveDetector(min_scene_len=min_len), show_progress=True)
    # 检测出的是录制时间(物理文件位置); 存 scenes.json 时 ×SPEED 还原成真实时间
    scenes = [{"shot_id": i + 1,
               "start": round(s.get_seconds() * SPEED, 3),
               "end": round(e.get_seconds() * SPEED, 3)}
              for i, (s, e) in enumerate(raw)]
    if not scenes:
        sys.exit("[切片] 未检测到镜头, 视频可能无效")

    clips_dir = workdir / "clips"
    clips_dir.mkdir(exist_ok=True)
    print(f"[切片] {len(scenes)} 个镜头, 物理切片…")
    from scenedetect import split_video_ffmpeg
    split_video_ffmpeg(str(video), raw, output_dir=str(clips_dir), show_progress=True)

    frames_dir = workdir / "frames"
    frames_dir.mkdir(exist_ok=True)
    print("[切片] 抽关键帧…")
    for sc in scenes:
        dur = sc["end"] - sc["start"]
        for j, t in enumerate((sc["start"] + min(0.2, dur / 4),
                               sc["start"] + dur / 2)):
            t = pick_frame_time(t, sc["start"], sc["end"])
            out = frames_dir / f"shot{sc['shot_id']:04d}_{j}.jpg"
            if not out.exists():
                # t 是真实时间, 物理文件仍是录制时间, seek 需 ÷SPEED 换回
                ffmpeg("-ss", f"{t / SPEED:.3f}", "-i", str(video),
                       "-vframes", "1", "-vf", "scale=640:-2", str(out))

    scenes_file.write_text(json.dumps(scenes, ensure_ascii=False, indent=1))
    return scenes


# ---------- 台词转写 ----------

def parse_vtt(text: str) -> list[dict]:
    """解析 VTT 字幕成 transcript 结构。YouTube 自动字幕是滚动式(每条 cue 带上一行残留),
    取每条 cue 最后一行并对相邻重复去重。speaker 留空, 由反向剧本阶段结合画面推断。"""
    # ponytail: 滚动字幕启发式去重, 需要逐词精确时间戳时改抓 json3 格式解析
    cue_re = re.compile(r"(\d+):(\d+):(\d+)\.(\d+) --> (\d+):(\d+):(\d+)\.(\d+)")
    lines, prev = [], None
    for block in re.split(r"\n\s*\n", text):
        m = cue_re.search(block)
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        body = block[m.end():]
        body = body.split("\n", 1)[1] if "\n" in body else ""  # 丢掉时间戳行剩余的定位参数
        cand = [ln.strip() for ln in re.sub(r"<[^>]+>", "", body).splitlines() if ln.strip()]
        if not cand or cand[-1] == prev:
            continue
        prev = cand[-1]
        lines.append({"start": round(h1 * 3600 + m1 * 60 + s1 + ms1 / 1000, 2),
                      "end": round(h2 * 3600 + m2 * 60 + s2 + ms2 / 1000, 2),
                      "speaker": "", "text": cand[-1]})
    return lines


def stage_transcript(video: Path, workdir: Path) -> list[dict]:
    from pydantic import BaseModel

    class Line(BaseModel):
        start: float
        end: float
        speaker: str
        text: str

    out_file = workdir / "transcript.json"
    if out_file.exists():
        print(f"[转写] 已存在, 跳过: {out_file}")
        return json.loads(out_file.read_text())

    subs = sorted(workdir.glob("subs*.vtt"))
    if subs:
        print(f"[转写] 使用字幕, 不调 Gemini: {subs[0].name}")
        lines = parse_vtt(subs[0].read_text())
        out_file.write_text(json.dumps(lines, ensure_ascii=False, indent=1))
        return lines

    load_env_key()  # Gemini 只在无字幕时兜底转写(Claude 不支持音频输入)
    from google import genai
    client = genai.Client()

    audio = workdir / "audio.mp3"
    if not audio.exists():
        print("[转写] 提取音频…")
        tmp = workdir / "audio.tmp.mp3"
        # 倍速录制时用 atempo 把音频降回正常速, ASR 质量和时间戳都按真实值
        af = ["-filter:a", f"atempo={1 / SPEED:.4f}"] if SPEED != 1.0 else []
        try:
            ffmpeg("-i", str(video), "-vn", *af, "-ac", "1", "-b:a", "64k", str(tmp))
        except subprocess.CalledProcessError:
            print("[转写] 视频无音轨, 台词为空")
            out_file.write_text("[]")
            return []
        tmp.rename(audio)

    # 分段写到临时目录再整体改名, 保证 chunk 集要么完整要么不存在
    chunk_dir = workdir / "audio_chunks"
    if not chunk_dir.exists():
        tmp_dir = workdir / "audio_chunks.tmp"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir()
        ffmpeg("-i", str(audio), "-f", "segment",
               "-segment_time", str(AUDIO_CHUNK_SEC), "-c", "copy",
               str(tmp_dir / "chunk_%03d.mp3"))
        tmp_dir.rename(chunk_dir)

    partial = workdir / "transcript.partial.jsonl"
    done = load_partial(partial)
    lines: list[dict] = []
    chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
    for i, chunk in enumerate(chunks):
        if i in done:
            lines.extend(done[i])
            continue
        print(f"[转写] {i + 1}/{len(chunks)} {chunk.name}")
        f = upload_ready(client, chunk)
        parsed = gen_json(
            client,
            [f, "逐句转写这段音频里的对白和旁白。start/end 为该句在音频内的秒数; "
                "speaker 用可区分的代号(如 男A/女B/旁白); text 为原话。没有语音则返回空列表。"],
            list[Line])
        offset = i * AUDIO_CHUNK_SEC
        chunk_lines = [{"start": round(ln.start + offset, 2),
                        "end": round(ln.end + offset, 2),
                        "speaker": ln.speaker, "text": ln.text}
                       for ln in parsed]
        append_partial(partial, i, chunk_lines)
        lines.extend(chunk_lines)
        client.files.delete(name=f.name)

    out_file.write_text(json.dumps(lines, ensure_ascii=False, indent=1))
    partial.unlink(missing_ok=True)
    return lines


# ---------- 2.4 镜头视觉分析 ----------

def split_names(s: str) -> list[str]:
    return [c.strip() for c in re.split(r"[;；]", str(s)) if c.strip() and c.strip() != "无人物"]


def apply_mapping(rows: list[dict], mapping: dict) -> list[dict]:
    """把识别层的原始外貌描述替换成归并后的统一代号(去重保序), 原描述留在 characters_raw。"""
    for r in rows:
        codes = []
        for c in split_names(r.get("characters", "")):
            code = mapping.get(c, c)
            if code not in codes:
                codes.append(code)
        r["characters_raw"] = r.get("characters", "")
        r["characters"] = "; ".join(codes) if codes else "无人物"
    return rows


def stage_analyze(scenes: list[dict], workdir: Path) -> list[dict]:
    """两段式: 1) haiku 并行逐镜识别(只写外貌描述, 无全局代号) 2) sonnet 一次全局归并出统一代号。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    out_file = workdir / "shots.json"
    if out_file.exists():
        print(f"[分析] 已存在, 跳过: {out_file}")
        return json.loads(out_file.read_text())

    frames_dir = (workdir / "frames").resolve()
    keys = ("shot_id", "shot_size", "camera_move", "scene", "characters", "action", "mood")
    base_prompt = (
        "你在分析一部影视作品按镜头顺序抽取的关键帧, 每个镜头 2 张图。用 Read 工具查看下面列出的所有图片, 逐镜头分析。\n"
        '只输出一个 JSON 数组, 不要任何其他文字。每个元素: {"shot_id": 镜头号(int), '
        '"shot_size": "远景/全景/中景/近景/特写", "camera_move": "据两帧变化推断, 不确定填固定", '
        '"scene": "场景地点+时间氛围", "characters": "出场人物, 多人用分号隔开", '
        '"action": "主要动作/事件, 一句话", "mood": "情绪基调"}。全部用中文。\n'
        "characters 规则: 每人写一段简短可辨识的外貌描述(性别+发型发色+服装等稳定特征, 不用逗号), "
        "不要起代号编号; 群众演员写群体名(如 啦啦队员们); "
        "虚焦/仅手部/背对镜头等拍摄状态写进 action 而不是 characters; 无人则写 无人物。\n")

    # ---- 第 1 段: 并行识别 (haiku) ----
    partial = workdir / "shots.partial.jsonl"
    done = load_partial(partial)
    batches = [scenes[i:i + SHOTS_PER_BATCH] for i in range(0, len(scenes), SHOTS_PER_BATCH)]
    lock = threading.Lock()

    def run_batch(bi):
        batch = batches[bi]
        prompt = base_prompt
        for sc in batch:
            imgs = " ".join(str(frames_dir / f"shot{sc['shot_id']:04d}_{j}.jpg")
                            for j in range(FRAMES_PER_SHOT)
                            if (frames_dir / f"shot{sc['shot_id']:04d}_{j}.jpg").exists())
            prompt += f"镜头 {sc['shot_id']} (时长 {sc['end'] - sc['start']:.1f}s): {imgs}\n"
        rows = [{k: r.get(k, "") for k in keys} for r in claude_json(prompt, RECOG_MODEL)]
        missing = {sc["shot_id"] for sc in batch} - {r["shot_id"] for r in rows}
        if missing:
            print(f"  ! batch {bi + 1} 缺少镜头分析: {sorted(missing)}")
        with lock:
            append_partial(partial, bi, rows)
        print(f"[识别] batch {bi + 1}/{len(batches)} 完成")
        return bi, rows

    todo = [bi for bi in range(len(batches)) if bi not in done]
    if todo:
        print(f"[识别] {len(todo)}/{len(batches)} 批待跑, {RECOG_MODEL} x{PARALLEL} 并行…")
        with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
            for bi, rows in ex.map(run_batch, todo):
                done[bi] = rows
    results = [r for bi in sorted(done) for r in done[bi]]

    # ---- 第 2 段: 全局归并 (sonnet) ----
    map_file = workdir / "character_map.json"
    if map_file.exists():
        merged = json.loads(map_file.read_text())
    else:
        junk_re = re.compile(r"虚焦|背对|仅.{0,4}(可见|入镜|特写)|仅手部|仅见|无法辨|轮廓|不可辨|身影模糊")
        all_chars = sorted({c for r in results for c in split_names(r.get("characters", ""))})
        junk = [c for c in all_chars if junk_re.search(c)]
        uniq_chars = [c for c in all_chars if not junk_re.search(c)]
        uniq_scenes = sorted({str(r.get("scene", "")).strip() for r in results if str(r.get("scene", "")).strip()})
        print(f"[归并] 人物描述 {len(uniq_chars)} 条(另 {len(junk)} 条拍摄状态直接归'未辨认') / "
              f"场景写法 {len(uniq_scenes)} 条, {MERGE_MODEL} 归并…")

        char_rule = ("把指向同一人物的外貌描述编号归为一组: 主要人物代号用 性别+字母(男A/女B...), "
                     "群众演员归入群体名(如 啦啦队员们)。同一人可能换装, 结合发型/体貌判断。")
        scene_rule = "把指向同一地点的场景写法编号归为一组, 组名用规范场景名(保留 日/夜 差异, 同地点不同时段算不同场景)。"

        def merge_groups(items, rule, chunk=120):
            """分块滚动归并: 每块带上已有分组名, 模型只回编号, 输出规模有界。"""
            groups: dict[str, dict] = {}
            for start in range(0, len(items), chunk):
                part = items[start:start + chunk]
                listing = "\n".join(f"{start + i}: {t}" for i, t in enumerate(part))
                prompt = ("对下面带编号的描述做归组。" + rule + "\n"
                          "直接按语义分组, 不要过度分析。"
                          '只输出 JSON: {"groups": [{"code": "组名", "appearance": "规范描述一句话", '
                          '"alias_ids": [编号]}]}。每个编号必须恰好出现在一组里。\n')
                if groups:
                    known = json.dumps([{"code": k, "appearance": v.get("appearance", "")}
                                        for k, v in groups.items()], ensure_ascii=False)
                    prompt += f"已有分组(同一人物/地点必须沿用原组名): {known}\n"
                prompt += f"\n描述列表:\n{listing}\n"
                raw = claude_json(prompt, MERGE_MODEL, timeout=1200)
                for g in raw.get("groups", []):
                    code = str(g.get("code", "")).strip()
                    if not code:
                        continue
                    grp = groups.setdefault(code, {"appearance": g.get("appearance", ""), "aliases": []})
                    grp["aliases"] += [items[i] for i in g.get("alias_ids", []) if 0 <= i < len(items)]
            return groups

        cgroups = merge_groups(uniq_chars, char_rule)
        if junk:
            cgroups.setdefault("未辨认", {"appearance": "拍摄状态不可辨认", "aliases": []})["aliases"] += junk
        sgroups = merge_groups(uniq_scenes, scene_rule)
        merged = {"characters": [{"code": k, "appearance": v.get("appearance", ""), "aliases": v["aliases"]}
                                 for k, v in cgroups.items()],
                  "scenes": [{"name": k, "aliases": v["aliases"]} for k, v in sgroups.items()]}
        lost = set(all_chars) - {a for c in merged["characters"] for a in c["aliases"]}
        if lost:
            print(f"  ! 归并遗漏 {len(lost)} 条人物描述(保留原文): {sorted(lost)[:5]}…")
        map_file.write_text(json.dumps(merged, ensure_ascii=False, indent=1))

    char_map = {a: c["code"] for c in merged.get("characters", []) for a in c.get("aliases", [])}
    scene_map = {a: s["name"] for s in merged.get("scenes", []) for a in s.get("aliases", [])}
    results = apply_mapping(results, char_map)
    for r in results:
        r["scene"] = scene_map.get(str(r.get("scene", "")).strip(), r.get("scene", ""))

    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    partial.unlink(missing_ok=True)
    return results


# ---------- 合并分镜表 ----------

def merge_storyboard(scenes: list[dict], shots: list[dict], lines: list[dict]) -> list[dict]:
    info = {s["shot_id"]: s for s in shots}
    board = []
    for sc in scenes:
        # 台词按中点落在镜头区间内归属
        dialog = [f'{ln["speaker"]}: {ln["text"]}' for ln in lines
                  if sc["start"] <= (ln["start"] + ln["end"]) / 2 < sc["end"]]
        row = {"shot_id": sc["shot_id"],
               "timecode": f'{fmt_tc(sc["start"])}-{fmt_tc(sc["end"])}',
               "duration": round(sc["end"] - sc["start"], 1),
               **{k: info.get(sc["shot_id"], {}).get(k, "") for k in
                  ("shot_size", "camera_move", "scene", "characters", "action", "mood")},
               "dialogue": " / ".join(dialog)}
        board.append(row)
    return board


def stage_storyboard(scenes, shots, lines, workdir: Path):
    board = merge_storyboard(scenes, shots, lines)
    (workdir / "storyboard.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=1))

    headers = ["镜号", "时间码", "时长(s)", "景别", "运镜", "场景", "人物", "动作", "情绪", "台词"]
    keys = ["shot_id", "timecode", "duration", "shot_size", "camera_move",
            "scene", "characters", "action", "mood", "dialogue"]
    md = ["| " + " | ".join(headers) + " |",
          "|" + "---|" * len(headers)]
    for row in board:
        md.append("| " + " | ".join(str(row[k]).replace("|", "/").replace("\n", " ") for k in keys) + " |")
    (workdir / "storyboard.md").write_text("\n".join(md))
    print(f"[分镜表] {len(board)} 镜 -> {workdir / 'storyboard.md'}")


# ---------- 入口 ----------

# --force-from 各阶段需要清掉的产物(含下游)
STAGE_OUTPUTS = {
    "scenes": ["scenes.json", "clips", "frames",
               "shots.json", "shots.partial.jsonl", "storyboard.json", "storyboard.md"],
    "transcript": ["audio.mp3", "audio_chunks", "transcript.json", "transcript.partial.jsonl",
                   "storyboard.json", "storyboard.md"],
    "analyze": ["shots.json", "shots.partial.jsonl", "character_map.json",
                "storyboard.json", "storyboard.md"],
}


def load_env_key():
    if os.environ.get("GEMINI_API_KEY"):
        return
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip("'\"")
                return
    sys.exit("缺少 GEMINI_API_KEY: 设环境变量, 或在 skill 目录放 .env (GEMINI_API_KEY=...)")


def default_name(url: str) -> str:
    return re.sub(r"\W+", "_", url.split("://")[-1]).strip("_")[:60]


def self_test():
    scenes = [{"shot_id": 1, "start": 0.0, "end": 5.0},
              {"shot_id": 2, "start": 5.0, "end": 9.0}]
    shots = [{"shot_id": 1, "shot_size": "中景", "camera_move": "固定",
              "scene": "白天 教室", "characters": "男A", "action": "起身", "mood": "紧张"}]
    lines = [{"start": 1.0, "end": 2.0, "speaker": "男A", "text": "你好"},
             {"start": 4.5, "end": 6.0, "speaker": "女B", "text": "再见"},  # 中点5.25 -> 镜2
             {"start": 9.5, "end": 10.0, "speaker": "旁白", "text": "越界"}]  # 不属于任何镜头
    board = merge_storyboard(scenes, shots, lines)
    assert board[0]["dialogue"] == "男A: 你好"
    assert board[1]["dialogue"] == "女B: 再见"
    assert board[1]["shot_size"] == ""  # 缺分析信息不崩
    assert board[0]["timecode"] == "00:00:00-00:00:05"

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.partial.jsonl"
        append_partial(p, 0, [{"a": 1}])
        append_partial(p, 2, [{"b": "中文"}])
        assert load_partial(p) == {0: [{"a": 1}], 2: [{"b": "中文"}]}

    assert default_name("https://www.youtube.com/watch?v=abc_123") == "www_youtube_com_watch_v_abc_123"

    # --speed 时间码换算方向: 录制时间 ×SPEED = 真实时间; 抽帧 seek ÷SPEED 换回录制时间
    rec, spd = 10.0, 1.5
    assert round(rec * spd, 3) == 15.0           # 录制10s → 真实15s
    assert round((rec * spd) / spd, 3) == rec    # 真实15s seek 回 10s
    assert round(1 / spd, 4) == 0.6667           # atempo 因子

    assert extract_json('前言\n[{"shot_id": 1, "scene": "教室"}]\n后记') == [{"shot_id": 1, "scene": "教室"}]
    assert extract_json('{"characters": [], "scenes": []}') == {"characters": [], "scenes": []}
    assert extract_json("没有json") is None
    assert extract_json("[断掉的json") is None

    rows = [{"characters": "深发红衣少女; 金发啦啦队员; 深发红衣少女"},
            {"characters": "无人物"}]
    mapped = apply_mapping(rows, {"深发红衣少女": "女A", "金发啦啦队员": "女C"})
    assert mapped[0]["characters"] == "女A; 女C", mapped
    assert mapped[0]["characters_raw"].startswith("深发红衣少女")
    assert mapped[1]["characters"] == "无人物"

    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000 align:start position:0%\nhello<00:00:02.000><c> there</c>\n\n"
           "00:00:03.000 --> 00:00:05.000 align:start position:0%\nhello there\nsecond line\n\n"
           "00:00:05.000 --> 00:00:07.000\nsecond line\n\n"
           "00:00:07.000 --> 00:00:08.000\n\n")
    parsed = parse_vtt(vtt)
    assert [p["text"] for p in parsed] == ["hello there", "second line"], parsed
    assert parsed[0]["start"] == 1.0 and parsed[0]["end"] == 3.0

    # 抽帧避开控件入镜窗口
    global OVERLAYS
    OVERLAYS = [(10.0, 15.0)]
    assert pick_frame_time(12.0, 0.0, 20.0) == 15.1     # 挪到窗口后
    assert pick_frame_time(12.0, 0.0, 14.0) == 9.9      # 后面出镜头范围 → 挪到窗口前
    assert pick_frame_time(12.0, 11.0, 14.0) == 12.0    # 两边都挪不开 → 原样
    assert pick_frame_time(5.0, 0.0, 20.0) == 5.0       # 不在窗口内
    OVERLAYS = []
    print("self-test ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="YouTube 等视频链接 (yt-dlp 下载)")
    src.add_argument("--video", help="本地视频文件路径")
    src.add_argument("--self-test", action="store_true")
    ap.add_argument("--output-dir", default="output", help="输出根目录")
    ap.add_argument("--name", help="项目名 (默认取视频文件名/URL slug)")
    ap.add_argument("--force", action="store_true", help="删除整个项目目录全部重跑")
    ap.add_argument("--force-from", choices=STAGE_OUTPUTS, help="只重跑指定阶段及其下游")
    ap.add_argument("--skip-transcript", action="store_true", help="跳过台词转写")
    ap.add_argument("--download-only", action="store_true", help="只下载视频和字幕, 不做后续处理")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="源片录制倍速(如手机1.5倍速录屏填1.5); 时间码自动还原真实值, 范围1.0-2.0")
    ap.add_argument("--overlays", help="hg_split 产出的 ep_NNN.json, 抽关键帧时避开其中的控件入镜窗口")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    if not 1.0 <= args.speed <= 2.0:
        sys.exit("--speed 需在 1.0-2.0 之间(atempo 单滤镜上限); 更高倍速请拆链, 暂不支持")
    global SPEED, OVERLAYS
    SPEED = args.speed
    if SPEED != 1.0:
        print(f"[倍速] 源片按 {SPEED}x 录制, 时间码将还原为真实值")
    if args.overlays:
        # json 里的窗口是录像(墙钟)秒, 集内相对; 换成真实时间要 ×SPEED
        OVERLAYS = [(a * SPEED, b * SPEED) for a, b in json.loads(Path(args.overlays).read_text())["overlays"]]
        print(f"[抽帧] 将避开 {len(OVERLAYS)} 个控件入镜窗口")

    name = args.name or (Path(args.video).stem if args.video else default_name(args.url))
    workdir = Path(args.output_dir) / name
    if args.force and workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if args.force_from:
        for item in STAGE_OUTPUTS[args.force_from]:
            p = workdir / item
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

    # 同一项目目录只能对应一个源链接, 防止换 URL 后静默复用旧产物
    if args.url:
        url_file = workdir / "source_url.txt"
        if url_file.exists() and url_file.read_text().strip() != args.url:
            sys.exit(f"{workdir} 已属于另一个链接 ({url_file.read_text().strip()})。"
                     f"换 --name, 或 --force 重跑。")
        url_file.write_text(args.url)

    video = stage_download(args.url, workdir) if args.url else Path(args.video)
    if args.download_only:
        print(f"[下载] --download-only 完成: {video}")
        return
    scenes = stage_scenes(video, workdir)
    lines = [] if args.skip_transcript else stage_transcript(video, workdir)
    shots = stage_analyze(scenes, workdir)
    stage_storyboard(scenes, shots, lines, workdir)


if __name__ == "__main__":
    main()
