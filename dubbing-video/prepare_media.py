"""Validate episode assets and prepare source audio on Windows."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def run(command):
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Media command failed")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--bgm", required=True, type=Path)
    parser.add_argument("--sfx", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Business processing must run on Windows")
    if not args.ffmpeg:
        parser.error("Specify --ffmpeg or add FFmpeg to PATH")
    ffmpeg = Path(args.ffmpeg).resolve()
    ffprobe = ffmpeg.with_name("ffprobe.exe")
    output = args.output_dir.resolve()
    sources = {role: path.resolve() for role, path in
               (("video", args.video), ("bgm", args.bgm), ("sfx", args.sfx))}
    derived = [output / "source-audio.wav", output / "asr-source.wav",
               output / "media-manifest.json"]
    if any(path in sources.values() for path in derived):
        raise ValueError("Output paths must not replace source assets")
    if len(set(sources.values())) != 3:
        raise ValueError("Video, BGM and SFX must be separate files")
    records = {}
    for role, path in sources.items():
        if not path.is_file():
            raise ValueError(f"Missing {role}: {path}")
        probe = json.loads(run([str(ffprobe), "-v", "error", "-show_format",
                                "-show_streams", "-of", "json", str(path)]))
        if not any(s["codec_type"] == "audio" for s in probe["streams"]):
            raise ValueError(f"No audio in {role}")
        if role == "video" and not any(s["codec_type"] == "video" for s in probe["streams"]):
            raise ValueError("Video asset has no video stream")
        run([str(ffmpeg), "-v", "error", "-xerror", "-i", str(path),
             "-map", "0:a:0", *( ["-map", "0:v:0"] if role == "video" else []),
             "-f", "null", "-"])
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        records[role] = {"path": str(path), "bytes": path.stat().st_size,
                         "sha256": digest.hexdigest(), "decode_verified": True,
                         "duration": float(probe["format"]["duration"]),
                         "streams": probe["streams"]}
    output.mkdir(parents=True, exist_ok=True)
    for filename, options in (("source-audio.wav", []),
                              ("asr-source.wav", ["-ar", "16000", "-ac", "1"])):
        run([str(ffmpeg), "-v", "error", "-xerror", "-y", "-i", str(sources["video"]),
             "-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", *options, str(output / filename)])
    warnings = []
    for role in ("bgm", "sfx"):
        if abs(records[role]["duration"] - records["video"]["duration"]) > .15:
            warnings.append(f"{role}: duration differs by over 150 ms; alignment review required")
    if records["bgm"]["sha256"] == records["sfx"]["sha256"]:
        warnings.append("BGM and SFX are identical files; verify source labeling")
    manifest = {"assets": records, "prepared_audio": {
        "source": str(output / "source-audio.wav"), "asr": str(output / "asr-source.wav")},
        "dialogue_isolation_verified": False, "timeline_alignment_verified": False,
        "warnings": warnings,
        "notes": ["Audio extracted from first video audio stream; purity needs listening review.",
                  "Similar durations do not prove the tracks have the same starting point."]}
    (output / "media-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "prepared", "durations": {
        k: v["duration"] for k, v in records.items()}, "warnings": warnings,
        "manifest": str(output / "media-manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
