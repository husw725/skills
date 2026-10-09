"""Reviewed screenplay context: enrich dialogue without replacing the timed source."""
import json
from pathlib import Path


def load_screenplay_context(path, rows):
    context = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if context.get("schema_version") != 1 or not isinstance(context.get("sources"), list) or not context["sources"]:
        raise ValueError("Screenplay context needs schema_version 1 and source provenance")
    for source in context["sources"]:
        if not isinstance(source, dict) or not all(source.get(k) for k in ("filename", "sha256", "version")):
            raise ValueError("Screenplay source needs filename, sha256 and version")
    episodes = context.get("episodes")
    if not isinstance(episodes, dict):
        raise ValueError("Screenplay context needs episode mappings")
    for episode in {r["episode"] for r in rows}:
        section = episodes.get(episode)
        if not isinstance(section, dict) or section.get("match_status") != "matched_main_dialogue":
            raise ValueError(f"Review screenplay/subtitle version match for episode {episode} first")
        if not isinstance(section.get("script_excerpt"), str) or not section["script_excerpt"].strip():
            raise ValueError("Matching screenplay excerpt is required")
        source_rows = [r for r in rows if r["episode"] == episode]
        annotations = section.get("cue_annotations", {})
        if not isinstance(annotations, dict) or set(annotations) != {r["id"] for r in source_rows}:
            raise ValueError("Screenplay annotations must cover every requested cue exactly")
        for row in source_rows:
            note = annotations[row["id"]]
            if not isinstance(note, dict) or note.get("source_text") != row["text"]:
                raise ValueError(f"Screenplay annotation is stale for cue {row['id']}")
            if not isinstance(note.get("speaker"), str) or not note["speaker"]:
                raise ValueError("Screenplay cue speaker must be explicit or unknown")
            if not note.get("script_evidence"):
                raise ValueError("Screenplay annotation needs evidence, including uncertainty")
    return context


def context_for_rows(context, rows):
    if not context:
        return None
    return {"sources": context["sources"], "story_notes": context.get("story_notes", []),
            "authority": "Timed source is authoritative; screenplay is context only. Do not add absent dialogue.",
            "episodes": {episode: context["episodes"][episode]
                         for episode in dict.fromkeys(r["episode"] for r in rows)}}


def annotate_rows(rows, context):
    if not context:
        return rows
    return [{**row, "speaker": context["episodes"][row["episode"]]["cue_annotations"][row["id"]]["speaker"],
             "screenplay_annotation": context["episodes"][row["episode"]]["cue_annotations"][row["id"]],
             "speaker_audio_verified": False} for row in rows]
