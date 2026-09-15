#!/usr/bin/env python3
"""把 hg_capture.py 的分块录像按集切分。

输入: <dir>/capture_log.jsonl + <dir>/chunk_NNN.mp4
输出: <dir>/episodes/ep_NNN.mp4 + ep_NNN.json (起止、来源片段、控件入镜窗口[集内秒], 供 pipeline 抽帧时避开)

原理:
- 每次读状态记录了 (t 墙钟, cur 当前时码, chunk, off)。录制倍速 speed 下, 该集起点墙钟 = t - cur/speed;
  同一集多次读取取中位数, 抗单次 OCR 误差。集终点 = 下一集起点; 末集用 t + (tot-cur)/speed。
- 每块录像的起始墙钟 = 该块内任意日志的 t - off(取最小)。集区间落到块上再 ffmpeg 切; 跨块则切两段再拼。
- 控件入镜窗口: 读状态 [t-1.2, t+3.8]; goto(抽屉) [t-5.0, t+0.5]。只记录不剔除, 保持集内时间连续。
"""
import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

FF = "/opt/homebrew/bin/ffmpeg"
FP = "/opt/homebrew/bin/ffprobe"
# Pixel 7 横屏 2400x1080 录屏, 16:9 内容居中, 左右各 240px 黑边(cropdetect 实测), 裁掉省 20% 像素
CROP = "crop=1920:1080:240:0"
# x264 slow + 动画调优 + crf23: 实测 ep1 51.6MB→26.1MB, 对比 crf20 源 SSIM 0.992(crf20 0.994 / crf26 0.990 差别肉眼不可见)
# scrcpy 录像时间基是 1/1597725000 这种怪值, 原样带进 x264+mp4 会让帧时间戳乱序(实测负间隔 180/589 帧, 播放抖得晕),
# 必须强制恒定 30fps + 正常时间基(实测后每帧间隔恒 33ms)
ENC = ["-fps_mode", "cfr", "-r", "30", "-video_track_timescale", "30000",
       "-c:v", "libx264", "-preset", "slow", "-tune", "animation", "-crf", "23", "-c:a", "aac", "-b:a", "96k"]


def chunk_files(d: Path) -> dict[int, Path]:
    """{块号: 文件}; 首轮录的是 mp4 分块, 现在是单文件 mkv, 两种都认。"""
    return {int(p.stem.split("_")[1]): p for p in sorted(d.glob("chunk_*.m??")) if p.suffix in (".mp4", ".mkv")}


def probe_dur(p: Path) -> float:
    out = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def analyze(entries: list[dict], speed: float, chunk_durs: dict[int, float]) -> tuple[list[dict], dict[int, float]]:
    """纯计算, 便于自测: 返回 [{episode, start, end, overlays}] (墙钟) 和 chunk_start{chunk: 墙钟}。"""
    chunk_start: dict[int, float] = {}
    for e in entries:
        if e.get("off") is not None and e.get("chunk"):
            chunk_start[e["chunk"]] = min(chunk_start.get(e["chunk"], 1e18), e["t"] - e["off"])

    # 日志里有标题直读集号时, 只信标题: 计数器(boundary/episode 字段)会因短集被跳过而落后, 无标题的读数按它归属会把
    # 上一集起点拉偏并链式推后(实测第 701s 一条 ep=None 的读数归到第8集, 第11集算出负时长)
    has_title = any(e.get("ep") for e in entries if e["event"] == "state")
    ep = None
    est: dict[int, list[float]] = {}
    tot_reads: dict[int, list[float]] = {}
    overlays: list[tuple[float, float]] = []
    for e in entries:
        ev = e["event"]
        if ev == "goto":
            ep = e["episode"]
            overlays.append((e["t"] - 5.0, e["t"] + 0.5))
        elif ev == "boundary":
            if not has_title:
                ep = e["episode"]
        elif ev == "state":
            overlays.append((e["t"] - 1.2, e["t"] + 3.8))
            if e.get("ep"):
                ep = e["ep"]                 # 标题直读的集号最可靠; 且 state 行写在同次读取的 boundary 行之前
            elif has_title:
                continue                     # 标题没读出来的那次: 只记控件窗口, 不参与估计
            elif ep is None:
                ep = e.get("episode") or 1
            if e.get("cur") is not None:
                est.setdefault(ep, []).append(e["t"] - e["cur"] / speed)
            if e.get("tot") is not None:
                tot_reads.setdefault(ep, []).append(e["tot"])
    rec_end = max((chunk_start[c] + d for c, d in chunk_durs.items() if c in chunk_start), default=0)
    tots = {k: statistics.median(v) for k, v in tot_reads.items()}

    # 起点: 直读估计取中位数, 但必须 ≥ 上集起点 + 上集总长/speed - 3(亮背景帧上 cur 常被误读);
    # 全部不合理时链式推算 start_k = start_{k-1} + tot_{k-1}/speed。
    # 集号补齐成连续区间: 60s 轮询会整集跳过 25-35s 的短集(实测第7/11集), 没读数的集靠链式推算起点, 不能并进前一集
    seen = sorted(set(est) | set(tot_reads))
    eps = list(range(seen[0], seen[-1] + 1)) if seen else []
    starts: dict[int, float] = {}
    for i, k in enumerate(eps):
        cands = est.get(k, [])
        if i > 0 and eps[i - 1] in tots:
            lower = starts[eps[i - 1]] + tots[eps[i - 1]] / speed - 3
            cands = [c for c in cands if lower <= c <= lower + 60]
            starts[k] = statistics.median(cands) if cands else lower + 3
        else:
            starts[k] = statistics.median(cands) if cands else 0.0

    result = []
    for i, k in enumerate(eps):
        start = starts[k]
        if i + 1 < len(eps):
            end = starts[eps[i + 1]]
        else:
            end = start + tots[k] / speed if k in tots else rec_end
        end = min(end, rec_end) if rec_end else end
        ov = [(round(max(a, start) - start, 2), round(min(b, end) - start, 2)) for a, b in overlays if b > start and a < end]
        result.append({"episode": k, "start": round(start, 2), "end": round(end, 2), "overlays": ov,
                       "reads": len(est.get(k, []))})       # reads=0: 整集被跳过, 起止全靠推算, 分析前值得抽查
    return result, chunk_start


def pieces_for(start: float, end: float, chunk_start: dict[int, float], chunk_durs: dict[int, float]):
    """墙钟区间 → [(chunk, in_off, out_off)], 可跨块。"""
    out = []
    for c in sorted(chunk_start):
        cs, ce = chunk_start[c], chunk_start[c] + chunk_durs.get(c, 0)
        a, b = max(start, cs), min(end, ce)
        if b - a > 0.2:
            out.append((c, round(a - cs, 3), round(b - cs, 3)))
    return out


def cut(files: dict[int, Path], out: Path, episode: int, pieces, fast: bool = False):
    """fast=True: -c copy 无损快切, 切点落到前一个关键帧(scrcpy 每 20s 一个, 开头最多多出 ~20s 上集尾巴),
    不裁边不重编码, 全季 1 分钟 vs 1.3 小时; 只要剧本(视频直读)时用, 分镜表模式仍需精确切点+CFR 重编码。"""
    tmp = []
    for i, (c, a, b) in enumerate(pieces):
        src = files[c]
        seg = out / f"_ep{episode:03d}_part{i}.mp4"
        enc = ["-c", "copy"] if fast else ["-vf", CROP, *ENC]
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(a), "-to", str(b), "-i", str(src),
                        *enc, "-movflags", "+faststart", str(seg)], check=True)
        tmp.append(seg)
    final = out / f"ep_{episode:03d}.mp4"
    if len(tmp) == 1:
        tmp[0].rename(final)
    else:
        lst = out / f"_ep{episode:03d}_concat.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in tmp))
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(final)], check=True)
        for p in tmp:
            p.unlink()
        lst.unlink()
    return final


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="output/hg_capture")
    ap.add_argument("--speed", type=float, default=1.5, help="录制时的播放倍速")
    ap.add_argument("--fast", action="store_true", help="-c copy 无损快切(关键帧对齐, 开头可能多 ≤20s 上集尾巴); 只要剧本时用")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    d = Path(args.dir)
    entries = [json.loads(l) for l in (d / "capture_log.jsonl").read_text().splitlines() if l.strip()]
    files = chunk_files(d)
    chunk_durs = {c: probe_dur(p) for c, p in files.items()}
    eps, chunk_start = analyze(entries, args.speed, chunk_durs)
    out = d / "episodes"
    out.mkdir(exist_ok=True)
    for e in eps:
        pcs = pieces_for(e["start"], e["end"], chunk_start, chunk_durs)
        if not pcs:
            print(f"ep{e['episode']}: 区间落在录像之外, 跳过")
            continue
        f = cut(files, out, e["episode"], pcs, fast=args.fast)
        meta = {**e, "pieces": pcs, "speed": args.speed, "duration_wall": round(e["end"] - e["start"], 2),
                "duration_content": round((e["end"] - e["start"]) * args.speed, 2)}
        (out / f"ep_{e['episode']:03d}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        print(f"ep{e['episode']:>3}: {meta['duration_content']:.0f}s 内容 ({meta['duration_wall']:.0f}s 录像) "
              f"pieces={pcs} overlays={len(e['overlays'])} -> {f.name}")


def self_test():
    # 1.5x: t=100 读到 cur=12 → 起点 92; 第2集 t=200 cur=6 → 196; 块1从墙钟 0 起 400s, 块2从 397.5 起
    log = [
        {"event": "start", "t": 0.0, "chunk": 1, "off": 0.0},
        {"event": "goto", "episode": 1, "t": 6.0, "chunk": 1, "off": 6.0},
        {"event": "state", "t": 100.0, "cur": 12, "tot": 149, "chunk": 1, "off": 100.0},
        {"event": "state", "t": 160.0, "cur": 102, "tot": 149, "chunk": 1, "off": 160.0, "episode": 1},
        {"event": "boundary", "episode": 2, "t": 200.0, "chunk": 1, "off": 200.0},
        {"event": "state", "t": 200.0, "cur": 6, "tot": 150, "chunk": 1, "off": 200.0, "episode": 2},
        {"event": "state", "t": 420.0, "cur": 96, "tot": 150, "chunk": 2, "off": 22.5, "episode": 2},
    ]
    eps, cs = analyze(log, 1.5, {1: 400.0, 2: 300.0})
    assert cs == {1: 0.0, 2: 397.5}, cs
    assert eps[0]["episode"] == 1 and eps[0]["start"] == 92.0, eps[0]
    # 第2集两次直读: 200-4=196(合理), 420-64=356(坏读数, 超出 上集起点+149/1.5-3=188.3 的 +60 窗口 → 丢弃)
    assert eps[1]["episode"] == 2 and eps[1]["start"] == 196.0 and eps[0]["end"] == 196.0, eps
    # 末集终点 = 起点 + 总长/speed = 196 + 150/1.5 = 296, 且不超录像末尾 697.5
    assert eps[1]["end"] == 296.0, eps[1]
    pcs = pieces_for(390.0, 410.0, cs, {1: 400.0, 2: 300.0})
    assert pcs == [(1, 390.0, 400.0), (2, 0.0, 12.5)], pcs          # 跨块切分
    assert all(0 <= a < b for a, b in eps[0]["overlays"]), eps[0]["overlays"]
    # 真实日志形状: state 带直读 ep=2 且写在 boundary 之前 → 必须归到第2集(而非当时的 episode=1)
    log2 = [
        {"event": "start", "t": 0.0, "chunk": 1, "off": 0.0},
        {"event": "goto", "episode": 1, "t": 5.83, "chunk": 1, "off": 5.83},
        {"event": "state", "t": 14.17, "cur": 12, "tot": 149, "ep": 1, "chunk": 1, "off": 14.17},
        {"event": "state", "t": 61.77, "cur": 83, "tot": 149, "ep": 1, "episode": 1, "chunk": 1, "off": 61.77},
        {"event": "state", "t": 109.54, "cur": 5, "tot": 138, "ep": 2, "episode": 1, "chunk": 1, "off": 109.54},
        {"event": "boundary", "episode": 2, "via": "title", "t": 109.54, "chunk": 1, "off": 109.54},
    ]
    e2, _ = analyze(log2, 1.5, {1: 400.0})
    assert [x["episode"] for x in e2] == [1, 2], e2
    assert abs(e2[1]["start"] - (109.54 - 5 / 1.5)) < 0.01 and e2[0]["end"] == e2[1]["start"], e2   # 106.21
    assert abs(e2[1]["end"] - (e2[1]["start"] + 138 / 1.5)) < 0.01, e2
    # 某集所有 cur 读数都不合理(无直读 ep) → 链式推算起点(复现首轮实测: 第2集 cur 误读 127)
    log3 = [
        {"event": "start", "t": 0.0, "chunk": 1, "off": 0.0},
        {"event": "goto", "episode": 1, "t": 5.9, "chunk": 1, "off": 5.9},
        {"event": "state", "t": 13.95, "cur": 12, "tot": 149, "chunk": 1, "off": 13.95},
        {"event": "boundary", "episode": 2, "t": 139.2, "chunk": 1, "off": 139.2},
        {"event": "state", "t": 139.2, "cur": 127, "tot": 138, "chunk": 1, "off": 139.2, "episode": 2},
    ]
    e3, _ = analyze(log3, 1.5, {1: 400.0})
    assert abs(e3[0]["start"] - 5.95) < 0.01 and abs(e3[1]["start"] - (5.95 + 149 / 1.5)) < 0.01, e3   # 链式: 105.28
    # 短集整集被 60s 轮询跳过(实测 6→8): 第7集无任何读数, 起点=第6集起点+117/1.5=84, 终点=第8集起点 110-15/1.5=100
    log4 = [
        {"event": "start", "t": 0.0, "chunk": 1, "off": 0.0},
        {"event": "state", "t": 10.0, "cur": 6, "tot": 117, "ep": 6, "chunk": 1, "off": 10.0},
        {"event": "state", "t": 110.0, "cur": 15, "tot": 72, "ep": 8, "chunk": 1, "off": 110.0},
    ]
    e4, _ = analyze(log4, 1.5, {1: 400.0})
    assert [x["episode"] for x in e4] == [6, 7, 8] and [x["reads"] for x in e4] == [1, 0, 1], e4
    assert e4[1]["start"] == 84.0 and e4[1]["end"] == 100.0 and e4[0]["end"] == 84.0, e4
    # 复现实测: 第9集尾一条读数标题没读出来(ep=None), 计数器 boundary 说是第8集 → 必须忽略, 否则第8集起点被拉到中位数 595
    log5 = [
        {"event": "start", "t": 0.0, "chunk": 1, "off": 0.0},
        {"event": "state", "t": 576.1, "cur": 8, "tot": 72, "ep": 8, "chunk": 1, "off": 576.1},
        {"event": "state", "t": 638.6, "cur": 29, "tot": 125, "ep": 9, "chunk": 1, "off": 638.6},
        {"event": "boundary", "episode": 8, "t": 638.6, "chunk": 1, "off": 638.6},
        {"event": "state", "t": 701.5, "cur": 123, "tot": 125, "ep": None, "episode": 8, "chunk": 1, "off": 701.5},
        {"event": "state", "t": 764.1, "cur": 91, "tot": 141, "ep": 10, "chunk": 1, "off": 764.1},
    ]
    e5, _ = analyze(log5, 1.5, {1: 1200.0})
    assert [x["reads"] for x in e5] == [1, 1, 1], e5
    assert abs(e5[0]["start"] - (576.1 - 8 / 1.5)) < 0.01 and abs(e5[1]["start"] - (638.6 - 29 / 1.5)) < 0.01, e5
    assert all(x["end"] > x["start"] for x in e5), e5
    print("self-test ok: 起点估算/坏读数过滤/直读ep归属/链式兜底/跨块映射/末集终点/入镜窗口/跳过短集补齐/无标题读数忽略")


if __name__ == "__main__":
    main()
