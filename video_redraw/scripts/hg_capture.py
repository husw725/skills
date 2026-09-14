#!/usr/bin/env python3
"""红果短剧 无人录屏采集: 一次点播 + 自动连播 + 分块录制 + 看门狗 + 换集边界日志。

前提(一次性手动): 手机 USB 调试已授权, 红果全屏播放器停在目标起始集开头(暂停/播放均可), 倍速已设好。
产出: <out>/chunk_NNN.mp4 (scrcpy 分块录像) + <out>/capture_log.jsonl (每次读状态/换集/点击的时刻),
      供 hg_split.py 按集切分并剔除控件入镜片段。

已实测的交互规则(Pixel 7, 2400x1080 横屏):
- 控件隐藏时 tap 中央 = 只调出控件(不改播放态); 控件显示时 tap 中央 = play/pause 切换。
- 控件约 3-5s 自动隐藏 → 两段式播放的第二下必须在第一下后 ~1s 内; 读状态的单点必须距上次 tap ≥5s。
- 播放态靠控件中央图标判: ▶=暂停, ⏸=播放(二值化模板匹配, 去背景画面干扰)。运动检测会被控件动画骗, 不用。
- 时码 OCR: 底部左=当前, 右=总长; 二值化 + psm6。总长变化 或 当前时码回退 = 换集。
- 「选集」抽屉: 点格子立即跳集并从 0:00 起播, 但抽屉不自动关; 抽屉开着时点视频区 = 关抽屉(不出控件)。
- 换集判定优先用标题 OCR 直读「第N集」, 读不到时退回时码回退/总长变化计数。
"""
import argparse
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

ADB = "/Users/husw/Library/Android/sdk/platform-tools/adb"
CENTER = (1200, 540)
BOX_CUR = (380, 800, 760, 910)      # 当前时码
BOX_TOT = (1900, 810, 2350, 900)    # 总时长
BOX_ICON = (1080, 420, 1320, 660)   # 中央播放图标
BOX_TITLE = (320, 90, 900, 170)     # 左上标题「万妖图录传第一季 第N集」(字高 y≈97-160, 全分辨率 OCR 定位)
BTN_EPISODES = (2099, 974)          # 控件行「选集」(全分辨率 OCR 定位, conf 96)
GRID_X0, GRID_Y0, GRID_DX, GRID_DY, GRID_COLS, GRID_ROWS = 1844, 227, 151, 147, 4, 6   # 选集抽屉格中心: 4 列 × 屏内 6 行
ASSETS = Path(__file__).resolve().parent / "hg_assets"
TC_RE = re.compile(r"(\d\d):(\d\d):(\d\d)")
EP_RE = re.compile(r"第\s*(\d+)\s*集")

_last_tap = 0.0


def sh(*cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def cap() -> Image.Image:
    return Image.open(io.BytesIO(sh(ADB, "exec-out", "screencap", "-p").stdout))


def tap(x=CENTER[0], y=CENTER[1]):
    global _last_tap
    sh(ADB, "shell", "input", "tap", str(x), str(y))
    _last_tap = time.time()


def _icon_bw(img):
    g = ImageOps.autocontrast(img.convert("L").crop(BOX_ICON)).resize((60, 60))
    return g.point(lambda v: 255 if v > 170 else 0)


def _mad(a, b):
    pa, pb = list(a.getdata()), list(b.getdata())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


_TPL = None


def icon_state(img) -> str:
    """'pause_icon'(=正在播放) / 'play_icon'(=暂停) / 'none'(控件未显示)"""
    global _TPL
    if _TPL is None:
        _TPL = (Image.open(ASSETS / "tpl_play_bw.png"), Image.open(ASSETS / "tpl_pause_bw.png"))
    bw = _icon_bw(img)
    white = sum(1 for v in bw.getdata() if v)
    if white < 60:                       # 中央没有白色图标 → 控件未显示
        return "none"
    d_play, d_pause = _mad(bw, _TPL[0]), _mad(bw, _TPL[1])
    return "play_icon" if d_play < d_pause else "pause_icon"


def ocr_tc(img, box):
    """多种预处理依次尝试, 首个匹配 HH:MM:SS 的胜出: 亮背景帧(金光/爆闪)会把单一阈值的二值化淹没。"""
    import pytesseract
    crop = img.crop(box).convert("L")
    big = crop.resize((crop.width * 4, crop.height * 4))
    ac = ImageOps.autocontrast(big)
    variants = (
        big.point(lambda p: 255 if p > 245 else 0),   # 只留纯白数字, 抗亮背景
        ac.point(lambda p: 255 if p > 170 else 0),    # 暗背景下最稳
        ac,                                            # 兜底
    )
    for v in variants:
        m = TC_RE.search(pytesseract.image_to_string(
            v, config="--psm 6 -c tessedit_char_whitelist=0123456789:"))
        if m:
            return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    return None


def read_episode_no(img):
    """从控件标题 OCR 集号(chi_sim), 多种预处理依次尝试(亮背景帧要先高阈值二值化只留白字); 读不到返回 None。"""
    import pytesseract
    crop = img.crop(BOX_TITLE).convert("L")
    big = crop.resize((crop.width * 3, crop.height * 3))
    for v in (big.point(lambda p: 255 if p > 225 else 0),
              big.point(lambda p: 255 if p > 245 else 0),
              ImageOps.autocontrast(big)):
        m = EP_RE.search(pytesseract.image_to_string(v, lang="chi_sim+eng", config="--psm 7"))
        if m:
            return int(m[1])
    return None


def grid_layout(img):
    """选集抽屉当前屏: (首个完整格的集号, [每行中心 y])。抽屉是可滚动网格(无分页标签), 打开时自动滚到当前集附近,
    滚动位置不一定整行对齐(实测 --goto 48 按固定行高点到了 44), 所以行的 y 从像素上扫: 沿格子左缘内侧一列,
    亮度 >32 的连续段就是格(背景 22 / 格 46 / 数字 130), 高度不足 100 的是被裁掉的半格, 跳过。抽屉没开返回 (None, [])。"""
    import pytesseract
    g = img.convert("L")
    x = GRID_X0 - 45
    col = [g.getpixel((x, y)) for y in range(0, g.height)]
    rows, start = [], None
    for y, v in enumerate(col + [0]):
        if v > 32 and start is None:
            start = y
        elif v <= 32 and start is not None:
            if y - start >= 100:
                rows.append((start + y - 1) // 2)
            start = None
    if not rows:
        return None, []
    y = rows[0]
    crop = g.crop((GRID_X0 - 55, y - 40, GRID_X0 + 55, y + 40))
    big = crop.resize((crop.width * 4, crop.height * 4))
    for v in (ImageOps.autocontrast(big), big.point(lambda p: 255 if p > 120 else 0)):
        s = pytesseract.image_to_string(v, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
        if s.isdigit() and int(s) % GRID_COLS == 1 and int(s) < 1000:   # 首格必是 1/5/9/...(实测 35 曾被读成 395)
            return int(s), rows
    return None, rows


def open_drawer():
    """调出控件 → 点「选集」; 抽屉没开(上次读状态留下的控件正好在自动隐藏边缘, 首点被吞)就关掉/重来, 最多 3 次。"""
    for _ in range(3):
        wait = 5.5 - (time.time() - _last_tap)
        if wait > 0:
            time.sleep(wait)
        tap()
        time.sleep(1.0)                          # 控件出现
        tap(*BTN_EPISODES)
        time.sleep(2.5)                          # 抽屉展开
        base, rows = grid_layout(cap())
        if base is not None:
            return base, rows
        tap()                                    # 抽屉若半开则关掉; 否则只是切一下播放状态, 下一轮 ensure_playing 会纠正
    sys.exit("选集抽屉 3 次都没打开")


def goto_episode(n: int, log):
    """开抽屉 → 用首格集号 + 像素扫出的行位置定位第 n 集, 不在屏内就按行慢滑再读(最多 6 次) → 点它。点完立刻从 0:00 起播。"""
    time.sleep(6)                                # 上一进程可能刚点过屏, 等控件自动隐藏, 让第一下 tap 语义确定为「调出控件」
    base, rows = open_drawer()
    for _ in range(6):
        row, col = divmod(n - base, GRID_COLS)
        if 0 <= row < len(rows):
            tap(GRID_X0 + GRID_DX * col, rows[row])
            break
        need = row - (len(rows) - 1) if row >= len(rows) else row    # 正=内容上滑 need 行, 负=下滑
        dy = max(-4, min(4, need)) * GRID_DY                          # 每次最多滑 4 行, 慢滑抑制惯性, 读完再校正
        x, y0 = GRID_X0 + GRID_DX, 850 if dy > 0 else 300
        sh(ADB, "shell", "input", "swipe", str(x), str(y0), str(x), str(y0 - dy), "600")
        time.sleep(1.2)
        base, rows = grid_layout(cap())
        if base is None:
            sys.exit("滑动后选集抽屉首格 OCR 失败")
    else:
        sys.exit(f"选集抽屉滑了 6 次仍没找到第 {n} 集")
    time.sleep(2.0)                              # 已跳到第 n 集并从 0:00 起播, 但抽屉仍开着
    tap()                                        # 抽屉开着时点视频区 = 关抽屉(不是调出控件)
    log({"event": "goto", "episode": n})         # 此前 ~2s 画面右侧有抽屉入镜, 切分时可据此裁掉


def read_state() -> dict:
    """无损读状态: 距上次 tap ≥5s 后单点调出控件并截屏。只做快速图标判别; 慢的时码 OCR 留给调用方。"""
    wait = 5.2 - (time.time() - _last_tap)
    if wait > 0:
        time.sleep(wait)
    tap()
    time.sleep(1.0)
    img = cap()
    return {"icon": icon_state(img), "img": img}


def ensure_playing(log) -> dict:
    """读状态; 若暂停则趁控件仍显示立刻补第二下(=播放); 之后再做慢 OCR, 免得控件在 OCR 期间隐藏。"""
    st = read_state()
    if st["icon"] == "play_icon":
        tap()                            # 距调出控件 ~1.3s, 控件仍在 → 这一下是播放
        log({"event": "resume"})
    elif st["icon"] == "none":
        log({"event": "controls_missing"})   # 可能已离开播放器, 交给上层判断
    st["cur"], st["tot"] = ocr_tc(st["img"], BOX_CUR), ocr_tc(st["img"], BOX_TOT)
    st["ep"] = read_episode_no(st["img"])
    return st


class Recorder:
    """scrcpy 单文件连续录制, 容器用 MKV: 没有 trailer 也能读, 崩了不丢已录内容, 所以不再按 --time-limit 分块。
    (首轮用 mp4 每 1200s 分块, 换块只在 60s 看门狗轮询里做, 每次换块丢 ~55s 录像, 8 集内容残缺。)
    只有 scrcpy 意外退出时 tick() 才补开下一段 chunk_00N.mkv。"""

    def __init__(self, out: Path):
        self.out, self.n, self.proc, self.started = out, 0, None, None

    def start_chunk(self):
        self.n += 1
        f = self.out / f"chunk_{self.n:03d}.mkv"
        self.proc = subprocess.Popen(
            ["scrcpy", "--no-playback", "--max-fps", "30", "--video-bit-rate", "12M", "--record", str(f)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(2.5)                  # scrcpy 起流
        self.started = time.time()
        return f

    def offset(self):
        return round(time.time() - self.started, 2)

    def tick(self):
        """scrcpy 意外死了(USB 抖动等) → 补开下一段, 日志里 chunk 号随之 +1。"""
        if self.proc and self.proc.poll() is not None:
            self.start_chunk()

    def stop(self):
        """Ctrl+C 的真实语义是给整个进程组发 SIGINT(含 adb 子进程); 只发给 scrcpy 本体它不会收场, 文件无 moov。
        实测进程组 SIGINT 0.1s 退出且 moov 完整。"""
        if self.proc and self.proc.poll() is None:
            pg = os.getpgid(self.proc.pid)
            os.killpg(pg, signal.SIGINT)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(pg, signal.SIGTERM)
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="output/hg_capture", help="录像与日志输出目录")
    ap.add_argument("--episodes", type=int, default=81, help="预期总集数, 换集计数到此停止")
    ap.add_argument("--interval", type=int, default=90, help="看门狗读状态间隔(秒); 每次会让控件入镜~3s")
    ap.add_argument("--max-hours", type=float, default=3.0, help="总时长保险丝")
    ap.add_argument("--goto", type=int, help="开录后先跳到第 N 集(1-24)再起播, 保证该集从 0:00 完整入镜")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return

    # 后台 shell 启动的进程 SIGINT 是被忽略的(实测 kill -INT 无效), SIGTERM 也走 finally 收录, 否则末块无 moov
    def _term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = (out / "capture_log.jsonl").open("a")
    rec = Recorder(out)

    def log(d):
        d.update(t=round(time.time(), 2), chunk=rec.n, off=rec.offset() if rec.started else None)
        d.pop("img", None)
        logf.write(json.dumps(d, ensure_ascii=False) + "\n")
        logf.flush()
        print(json.dumps(d, ensure_ascii=False))

    rec.start_chunk()                    # 先开录, 跳集/起播全程入镜, 首集 0:00 不丢
    log({"event": "start"})
    episode = args.goto or 1
    try:                                 # goto/起播失败 sys.exit 也要走 finally 收录, 否则 scrcpy 成孤儿继续录(实测过)
        if args.goto:
            goto_episode(args.goto, log)
        st = ensure_playing(log)         # 起播(若停着) 并记录首个状态
        log({"event": "state", **{k: st[k] for k in ("icon", "cur", "tot", "ep")}})
        episode = st["ep"] or episode
        prev_cur, prev_tot, stuck, t0 = st["cur"], st["tot"], 0, time.time()
        while time.time() - t0 < args.max_hours * 3600:
            time.sleep(args.interval)
            rec.tick()
            st = ensure_playing(log)
            cur, tot = st["cur"], st["tot"]
            log({"event": "state", "icon": st["icon"], "cur": cur, "tot": tot, "ep": st["ep"], "episode": episode})
            # 标题直读集号采信 当前集..当前集+3(实测 60s 间隔会整集跳过 25-35s 的短集, 只认 +1 会让计数器落后; 误读如 7→71 不采信)
            title_ep = st["ep"] if st["ep"] is not None and episode <= st["ep"] <= episode + 3 else None
            if title_ep is not None and title_ep > episode:
                episode = title_ep
                log({"event": "boundary", "episode": episode, "via": "title"})
                if episode > args.episodes:
                    log({"event": "done", "reason": "reached target episodes"})
                    break
            if st["icon"] == "none":
                stuck += 1
                if stuck >= 3:
                    log({"event": "abort", "reason": "controls missing 3x (left player?)"})
                    break
                continue
            stuck = 0
            wrapped = (tot is not None and prev_tot is not None and tot != prev_tot or
                       cur is not None and prev_cur is not None and cur < prev_cur - 5)
            # 标题没给出可信集号时, 才用 总长变化/时码回退 计数兜底(与标题路径互斥, 否则同一读取会连跳两集)
            if title_ep is None and wrapped:
                episode += 1
                log({"event": "boundary", "episode": episode})
                if episode > args.episodes:
                    log({"event": "done", "reason": "reached target episodes"})
                    break
            # 标题仍是本集但时码回绕 = 同一集重播(实测末集播完 App 无下一集就循环), 到目标集数即停
            elif title_ep == episode and wrapped and tot == prev_tot:
                log({"event": "replay", "episode": episode})
                if episode >= args.episodes:
                    log({"event": "done", "reason": "last episode replaying"})
                    break
            # 卡在片尾不动(连播关掉了?) 连续 2 次 → 停
            if cur is not None and tot is not None and cur >= tot - 2 and prev_cur == cur:
                log({"event": "abort", "reason": "stuck at end, autoplay stopped?"})
                break
            prev_cur, prev_tot = cur, tot
    finally:
        rec.stop()
        log({"event": "stop", "episodes_seen": episode})
        logf.close()


def self_test():
    """用已知帧验证三个传感器(真实截图, 非合成)。"""
    playing = Image.open(ASSETS / "sample_playing.png")   # 已知 ⏸ 00:00:36/00:02:47
    paused = Image.open(ASSETS / "sample_paused.png")     # 已知 ▶ 00:00:18/00:02:47
    assert icon_state(playing) == "pause_icon", icon_state(playing)
    assert icon_state(paused) == "play_icon", icon_state(paused)
    assert ocr_tc(playing, BOX_CUR) == 36 and ocr_tc(playing, BOX_TOT) == 167, (ocr_tc(playing, BOX_CUR), ocr_tc(playing, BOX_TOT))
    assert ocr_tc(paused, BOX_CUR) == 18 and ocr_tc(paused, BOX_TOT) == 167, (ocr_tc(paused, BOX_CUR), ocr_tc(paused, BOX_TOT))
    # 无控件的纯画面应判 none(用 icon 区域全黑的合成图代替)
    assert icon_state(Image.new("RGB", (2400, 1080), (20, 20, 20))) == "none"
    # 标题集号: 暗背景帧 + 亮背景(金光)帧都是「第4集」
    assert read_episode_no(playing) == 4, read_episode_no(playing)
    assert read_episode_no(paused) == 4, read_episode_no(paused)
    # 真实抽屉截图(裁掉左侧视频区只留 x≥1700, 贴回原位): 滚到 29-52, 6 行完整格
    drawer = Image.new("L", (2400, 1080))
    drawer.paste(Image.open(ASSETS / "sample_drawer.png").convert("L"), (1700, 0))
    base, rows = grid_layout(drawer)
    assert base == 29 and rows == [234, 381, 528, 675, 822, 969], (base, rows)
    assert grid_layout(playing)[0] is None, "没开抽屉的帧不该读出首格集号"
    print("self-test ok: icon ▶/⏸ + 时码 OCR + 标题集号 + 选集抽屉行位/首格 在真实帧上全部通过")


if __name__ == "__main__":
    main()
