#!/usr/bin/env python3
"""把分集信息和录像分离, 让没有原始 chunk 的机器也能切集分析。

  build: 在采集机上, 从 capture_log + chunk 时长算出每集在「chunk 顺序拼接成的整片」里的起止 → episodes_index.json
  cut:   在任意机器上, 用整片(如 S3 上的 wytl_s1_720p.mp4) + index 切出 ep_NNN.mp4 + ep_NNN.json(与 hg_split 同格式,
         hg_batch_analyze.sh / pipeline --overlays 直接可用)

用法:
  python3 scripts/hg_cut_index.py build --dir output/wytl_s1                      # → output/wytl_s1/episodes_index.json
  python3 scripts/hg_cut_index.py cut --video wytl_s1_720p.mp4 --index episodes_index.json --out output/wytl_s1/episodes
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import hg_split as hs  # noqa: E402

FF = "ffmpeg"


def build(d: Path, speed: float) -> dict:
    entries = [json.loads(l) for l in (d / "capture_log.jsonl").read_text().splitlines() if l.strip()]
    durs = {c: hs.probe_dur(p) for c, p in hs.chunk_files(d).items()}
    eps, cstart = hs.analyze(entries, speed, durs)
    # 整片 = chunk 按序 concat, 块内偏移 + 前面各块时长之和 = 整片时间(块间的录制间隙在整片里不存在)
    cum, acc = {}, 0.0
    for c in sorted(durs):
        cum[c] = acc
        acc += durs[c]
    out = []
    for e in eps:
        pcs = hs.pieces_for(e["start"], e["end"], cstart, durs)
        if not pcs:
            continue
        c0, a, _ = pcs[0]
        c1, _, b = pcs[-1]
        out.append({"episode": e["episode"], "start": round(cum[c0] + a, 3), "end": round(cum[c1] + b, 3),
                    "overlays": e["overlays"], "reads": e["reads"]})
    return {"speed": speed, "source": "chunk_*.mp4 concat in order", "episodes": out}


def cut(video: Path, index: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    speed = index["speed"]
    for e in index["episodes"]:
        if e.get("damaged_content_sec"):
            print(f"ep{e['episode']:>3}: 缺 {e['damaged_content_sec']}s 内容(待重录), 跳过")
            continue
        f = out / f"ep_{e['episode']:03d}.mp4"
        if not f.exists():
            subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(e["start"]), "-to", str(e["end"]),
                            "-i", str(video), "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac", str(f)], check=True)
        wall = e["end"] - e["start"]
        (out / f"ep_{e['episode']:03d}.json").write_text(json.dumps(
            {**e, "speed": speed, "duration_wall": round(wall, 2), "duration_content": round(wall * speed, 2)},
            ensure_ascii=False, indent=1))
        print(f"ep{e['episode']:>3}: {wall * speed:.0f}s 内容 reads={e['reads']} -> {f.name}")


def self_test():
    # 两块各 100s, 块 2 实际晚 3s 才开录(录制间隙); 第 2 集跨块: 墙钟 90..130 → 整片 90..(100+27)=127
    eps = [{"episode": 1, "start": 10.0, "end": 90.0, "overlays": [], "reads": 1},
           {"episode": 2, "start": 90.0, "end": 130.0, "overlays": [(5.0, 10.0)], "reads": 1}]
    cstart, durs = {1: 0.0, 2: 103.0}, {1: 100.0, 2: 100.0}
    cum = {1: 0.0, 2: 100.0}
    got = []
    for e in eps:
        pcs = hs.pieces_for(e["start"], e["end"], cstart, durs)
        (c0, a, _), (c1, _, b) = pcs[0], pcs[-1]
        got.append((round(cum[c0] + a, 3), round(cum[c1] + b, 3)))
    assert got == [(10.0, 90.0), (90.0, 127.0)], got
    print("self-test ok: 跨块集在整片里的起止(块间隙被抹掉)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--dir", required=True)
    b.add_argument("--speed", type=float, default=1.5)
    c = sub.add_parser("cut")
    c.add_argument("--video", required=True)
    c.add_argument("--index", required=True)
    c.add_argument("--out", required=True)
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test()
    elif args.cmd == "build":
        idx = build(Path(args.dir), args.speed)
        p = Path(args.dir) / "episodes_index.json"
        p.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
        print(f"{len(idx['episodes'])} 集 -> {p}")
    else:
        cut(Path(args.video), json.loads(Path(args.index).read_text()), Path(args.out))


if __name__ == "__main__":
    main()
