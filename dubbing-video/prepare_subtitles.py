"""Import episode SRT files, retaining source cues and millisecond timecodes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from translate import load_segments, save_json, srt_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Business processing must run on Windows")
    sources = []
    for path in args.source_dir.rglob("*"):
        match = re.search(r"(?i)ep0*(\d+)", path.stem)
        if path.is_file() and path.suffix.lower() in (".srt", ".str", ".st") and match:
            sources.append((int(match[1]), path))
    if not sources:
        raise ValueError("No episode subtitles found")
    episodes = [ep for ep, _ in sources]
    if len(set(episodes)) != len(episodes):
        raise ValueError("Multiple source files for one episode; resolve versions first")
    output = args.output_dir.resolve()
    if output == args.source_dir.resolve() or args.source_dir.resolve() in output.parents:
        raise ValueError("Keep normalized outputs outside the original source directory")
    rows, manifest = [], []
    for episode, source in sorted(sources):
        raw = source.read_bytes()
        encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
        text = raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
        normalized = output / "normalized" / f"episode-{episode:02d}.en.srt"
        normalized.parent.mkdir(parents=True, exist_ok=True)
        normalized.write_text(text, encoding="utf-8")
        cues = load_segments(normalized)
        out_of_order = any(b["start"] < a["start"] for a,b in zip(cues,cues[1:]))
        for cue in cues:
            cue.update({"original_cue_id": cue["id"], "episode": str(episode),
                        "id": f"e{episode:02d}-{cue['id']}", "source_file": source.name,
                        "timing_source": "subtitle_display_window",
                        "speaker_verified": False, "speech_timing_verified": False})
        cues.sort(key=lambda c: (c["start"], c["end"]))
        # Preserve IDs and every timecode; repair ordering only, never retime dialogue.
        normalized.write_text("\n\n".join(
            f"{c['original_cue_id']}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}"
            for c in cues) + "\n", encoding="utf-8")
        manifest.append({"episode": episode, "source_file": source.name,
                         "source_sha256": hashlib.sha256(raw).hexdigest(), "encoding": encoding,
                         "extension_corrected": source.suffix.lower() != ".srt",
                         "cues": len(cues), "end": max(c["end"] for c in cues),
                         "out_of_order": out_of_order, "chronological_order_normalized": out_of_order})
        rows.extend(cues)
    save_json(output / "dialogue.en.json", {"segments": rows})
    # Validate the saved representation using the translation module, including global IDs.
    reread = load_segments(output / "dialogue.en.json")
    if reread != rows:
        raise ValueError("Saved subtitle representation differs from imported cues")
    save_json(output / "subtitle-manifest.json", {"episodes": manifest, "total_cues": len(rows)})
    script = "\n\n".join(f"EPISODE {ep}\n" + "\n".join(
        f"{c['id']} | {c['text']}" for c in rows if c["episode"] == str(ep)) for ep in sorted(episodes))
    (output / "series-source.txt").write_text(script + "\n", encoding="utf-8")
    print(json.dumps({"episodes": len(manifest), "cues": len(rows),
                      "corrected_extensions": [m["episode"] for m in manifest if m["extension_corrected"]],
                      "out_of_order_episodes": [m["episode"] for m in manifest if m["out_of_order"]]}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
