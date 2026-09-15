#!/usr/bin/env python3
"""把主采集 + 若干补录目录合成一部完整的 720p 全季整片, 并生成与之精确对应的 episodes_index.json。

每集直接从源录像(mp4 分块 / mkv)编成 720p 单集(裁黑边, CFR 30fps, x264 crf27, 参数完全一致), 4 路并行,
再无损 concat(带章节), 索引里的起止取自各单集实测时长, 不再依赖日志估算。

用法:
  python3 scripts/hg_build_full.py --main output/wytl_s1 --speed 1.5 \
      --fix output/wytl_fix_30:30,31 --fix output/wytl_fix_48:48 --fix output/wytl_fix_49:49 \
      --fix output/wytl_fix_65:65,66 --fix output/wytl_fix_79:79,80 \
      --out output/wytl_s1/wytl_s1_720p.mp4 --index output/wytl_s1/episodes_index.json
--fix DIR:EPS 里的集覆盖主目录同号集(主目录里它们是换块空档导致的残缺版)。
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import hg_split as hs  # noqa: E402

FF, FP = hs.FF, hs.FP
ENC = ["-vf", "crop=1920:1080:240:0,scale=1280:720", "-fps_mode", "cfr", "-r", "30", "-video_track_timescale", "30000",
       "-c:v", "libx264", "-preset", "medium", "-tune", "animation", "-crf", "27",
       "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "2"]


def plan(d: Path, speed: float, only=None):
    """{episode: (pieces, overlays, reads)} for one capture dir."""
    entries = [json.loads(l) for l in (d / "capture_log.jsonl").read_text().splitlines() if l.strip()]
    files = hs.chunk_files(d)
    durs = {c: hs.probe_dur(p) for c, p in files.items()}
    eps, cstart = hs.analyze(entries, speed, durs)
    out = {}
    for e in eps:
        if only is not None and e["episode"] not in only:
            continue
        pcs = hs.pieces_for(e["start"], e["end"], cstart, durs)
        if pcs:
            out[e["episode"]] = ([(files[c], a, b) for c, a, b in pcs], e["overlays"], e["reads"])
    return out


def encode(ep: int, pieces, tmp: Path) -> Path:
    final = tmp / f"ep_{ep:03d}.mp4"
    if final.exists():
        return final
    parts = []
    for i, (src, a, b) in enumerate(pieces):
        seg = tmp / f"_ep{ep:03d}_{i}.mp4"
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(a), "-to", str(b), "-i", str(src),
                        *ENC, str(seg)], check=True)
        parts.append(seg)
    if len(parts) == 1:
        parts[0].rename(final)
    else:
        lst = tmp / f"_ep{ep:03d}.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(final)], check=True)
        for p in parts:
            p.unlink()
        lst.unlink()
    print(f"ep{ep:>3} done", flush=True)
    return final


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True)
    ap.add_argument("--fix", action="append", default=[], help="DIR:ep,ep 覆盖主目录同号集")
    ap.add_argument("--speed", type=float, default=1.5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    plans = plan(Path(args.main), args.speed)
    for spec in args.fix:
        d, eps = spec.split(":")
        got = plan(Path(d), args.speed, only={int(x) for x in eps.split(",")})
        missing = {int(x) for x in eps.split(",")} - set(got)
        if missing:
            sys.exit(f"{d} 里没有第 {sorted(missing)} 集的完整读数")
        plans.update(got)
    eps = sorted(plans)
    assert eps == list(range(eps[0], eps[-1] + 1)), f"集号不连续: {eps}"
    tmp = Path(args.out).parent / "_build720"
    tmp.mkdir(exist_ok=True)
    with ThreadPoolExecutor(args.jobs) as ex:
        files = list(ex.map(lambda k: encode(k, plans[k][0], tmp), eps))

    lst = tmp / "_all.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in files))
    lines, t, index = [";FFMETADATA1"], 0.0, []
    for k, p in zip(eps, files):
        dur = hs.probe_dur(p)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}", f"END={int((t + dur) * 1000)}", f"title=第{k}集"]
        index.append({"episode": k, "start": round(t, 3), "end": round(t + dur, 3), "overlays": plans[k][1],
                      "reads": plans[k][2], "duration_content": round(dur * args.speed, 1)})
        t += dur
    meta = tmp / "_chapters.txt"
    meta.write_text("\n".join(lines) + "\n")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(meta), "-map_metadata", "1", "-c", "copy", "-movflags", "+faststart", args.out], check=True)
    Path(args.index).write_text(json.dumps(
        {"speed": args.speed, "source": Path(args.out).name, "note": "起止为整片内秒数(实测), 全部为完整集", "episodes": index},
        ensure_ascii=False, indent=1))
    print(f"{len(eps)} 集, {t / 60:.1f} min -> {args.out} ({Path(args.out).stat().st_size / 1048576:.0f} MB); 索引 -> {args.index}")


if __name__ == "__main__":
    main()
