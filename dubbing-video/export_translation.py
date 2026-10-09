"""Validate an edited translation against imported dialogue, then export on Windows."""
import argparse
import csv
from pathlib import Path
import sys

from screenplay_context import load_screenplay_context, annotate_rows

from translate import estimate_duration, fingerprint, load_segments, read_json, save_json, validate_bible, write_srt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("translation", type=Path)
    parser.add_argument("--screenplay-context", type=Path)
    parser.add_argument("--subtitle-only", action="store_true")
    parser.add_argument("--bible", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Business processing must run on Windows")
    source = load_segments(args.source)
    draft = read_json(args.translation)
    bible = read_json(args.bible)
    glossary = validate_bible(bible)
    episode = str(draft["episode"])
    source = [row for row in source if row["episode"] == episode]
    if not source:
        raise ValueError("Episode missing from source")
    canonical = [{k: row[k] for k in ("id", "text", "start", "end")} for row in source]
    if draft.get("source_fingerprint") != fingerprint(canonical):
        raise ValueError("Source content/timing differs from the translation's source")
    if not args.screenplay_context and not args.subtitle_only:
        parser.error("Provide --screenplay-context; subtitle-only is an explicit exception")
    screenplay = load_screenplay_context(args.screenplay_context, source) if args.screenplay_context else None
    source = annotate_rows(source, screenplay)
    if screenplay and draft.get("screenplay_context_fingerprint") != fingerprint(screenplay):
        raise ValueError("Translation was not reviewed against this screenplay context")
    entries = draft["segments"]
    by_id = {row["id"]: row for row in entries}
    if len(by_id) != len(entries) or set(by_id) != {row["id"] for row in source}:
        raise ValueError("Missing, extra, or duplicate translated IDs")
    rows = []
    for row in source:
        entry = by_id[row["id"]]
        text = entry["translation"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Blank translation")
        for name, target in glossary.items():
            if name in row["text"] and target not in text and target.lower() not in text.lower():
                raise ValueError(f"Locked name/term missing for {row['id']}: {target}")
        duration = estimate_duration(text)
        ratio = duration / (row["end"] - row["start"])
        rows.append({**row, "translation": text, "estimated_duration_s": duration,
                     "duration_ratio": round(ratio, 3), "timing_needs_review": abs(ratio - 1) > .2,
                     "tts_timing_verified": False, "emotion_verified": False,
                     "review_issues": entry.get("review_issues", []),
                     "translator_notes": entry.get("notes", ""),
                     "translation_backend": draft["translation_backend"]})
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / "translated.json", {"episode": episode, "language": "pt-BR",
        "source_fingerprint": draft["source_fingerprint"], "bible_fingerprint": fingerprint(bible),
        "screenplay_context_fingerprint": fingerprint(screenplay) if screenplay else None,
        "screenplay_sources": screenplay["sources"] if screenplay else [],
        "segments": rows, "review_method": "main assistant contextual semantic review; no independent native listening review"})
    write_srt(output / "translated.pt-BR.srt", rows)
    review = [r for r in rows if r["timing_needs_review"] or r["review_issues"]]
    save_json(output / "translated.review.json", {"segments": review,
        "notes": ["Duration is a syllable heuristic, not generated audio timing.",
                  "Source timestamps are subtitle display windows; voices and emotions need audio review."]})
    groups = draft.get("proposed_speech_groups", [])
    index = {row["id"]: i for i, row in enumerate(rows)}
    grouped = set()
    starts = {}
    for group in groups:
        if len(group) < 2 or any(sid not in index or sid in grouped for sid in group):
            raise ValueError("Invalid or overlapping proposed speech group")
        positions = [index[sid] for sid in group]
        if positions != list(range(positions[0], positions[0]+len(positions))):
            raise ValueError("Speech groups must preserve adjacent cue ordering")
        members = [rows[i] for i in positions]
        if any(b["start"]-a["end"] > .3 or b["start"] < a["start"] for a,b in zip(members,members[1:])):
            raise ValueError("Speech groups cannot absorb long pauses or reorder cues")
        if len({r["speaker"] for r in members}) != 1:
            raise ValueError("Speech groups cannot merge different screenplay speakers")
        grouped.update(group)
        starts[group[0]] = group
    units = []
    offset = 0
    while offset < len(rows):
        group = starts.get(rows[offset]["id"], [rows[offset]["id"]])
        members = rows[offset:offset+len(group)]
        units.append({"id": f"e{int(episode):02d}-utterance-{len(units)+1:03d}",
                      "cue_ids": group, "start": members[0]["start"], "end": max(r["end"] for r in members),
                      "text": " ".join(r["text"] for r in members),
                      "translation": " ".join(r["translation"] for r in members),
                      "source_cue_windows": [{k:r[k] for k in ("id","start","end")} for r in members],
                      "speaker": members[0]["speaker"], "speaker_audio_verified": False,
                      "screenplay_annotations": [r.get("screenplay_annotation") for r in members],
                      "grouping_verified": False, "tts_timing_verified": False})
        offset += len(group)
    save_json(output / "speech-units.draft.json", {"schema_version": 1, "language":"pt-BR",
        "notes": ["Proposed utterance grouping; verify against original audio before voice generation.",
                  "Future MCP adapter must handle speaker assignment and measured TTS timing."], "units": units})
    fields = ["id", "start", "end", "speaker", "text", "translation", "estimated_duration_s",
              "duration_ratio", "timing_needs_review", "tts_timing_verified", "translator_notes"]
    with (output / "translation-comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    reread = read_json(output / "translated.json")["segments"]
    if [(r["id"],r["start"],r["end"]) for r in reread] != [(r["id"],r["start"],r["end"]) for r in source]:
        raise ValueError("Saved translation changed source timestamps")
    print(f"Episode {episode}: exported {len(rows)} cues; {len(review)} require timing/source review")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
