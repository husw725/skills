import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import export_translation
import prepare_subtitles
from translate import fingerprint


class SubtitlePreparationTests(unittest.TestCase):
    def test_misnamed_srt_is_sorted_without_retiming_or_renumbering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original"
            source.mkdir()
            (source / "episode_EP01.str").write_text(
                "1\n00:00:03,001 --> 00:00:04,123\nLater\n\n"
                "2\n00:00:01,002 --> 00:00:02,234\nEarlier\n", encoding="utf-8")
            with patch.object(sys, "argv", ["prepare_subtitles.py", str(source), "--output-dir", str(root/"out")]), contextlib.redirect_stdout(io.StringIO()):
                prepare_subtitles.main()
            rows = json.loads((root/"out/dialogue.en.json").read_text())["segments"]
            self.assertEqual([(r["id"],r["start"],r["end"]) for r in rows],
                             [("e01-2",1.002,2.234),("e01-1",3.001,4.123)])
            self.assertTrue((source/"episode_EP01.str").read_text().startswith("1\n"))

    def fixture(self, root, change_source=False, omit_id=False, omit_name=False):
        rows = [{"id":"e01-1","episode":"1","text":"Laura","start":0.,"end":1.}]
        canonical = [{k:r[k] for k in ("id","text","start","end")} for r in rows]
        draft = {"episode":"1", "source_fingerprint":fingerprint(canonical),
                 "translation_backend":"fixture", "segments":[] if omit_id else
                 [{"id":"e01-1","translation":"Oi." if omit_name else "Laura"}]}
        if change_source:
            rows[0]["end"] = 1.5
        for name, value in (("source.json",{"segments":rows}),("draft.json",draft),
                            ("bible.json",{"glossary":[{"source":"Laura","target":"Laura","kind":"person"}]})):
            (root/name).write_text(json.dumps(value), encoding="utf-8")
        return ["export_translation.py",str(root/"source.json"),str(root/"draft.json"),
                "--bible",str(root/"bible.json"),"--output-dir",str(root/"out")]

    def test_rejects_translation_after_source_timecode_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = self.fixture(Path(directory), change_source=True)
            with patch.object(sys,"argv",argv), self.assertRaisesRegex(ValueError,"differs"):
                export_translation.main()

    def test_rejects_missing_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = self.fixture(Path(directory), omit_id=True)
            with patch.object(sys,"argv",argv), self.assertRaisesRegex(ValueError,"Missing"):
                export_translation.main()

    def test_rejects_dropped_character_name(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = self.fixture(Path(directory), omit_name=True)
            with patch.object(sys,"argv",argv), self.assertRaisesRegex(ValueError,"missing"):
                export_translation.main()

    def test_exports_original_timecodes_without_claiming_audio_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(sys,"argv",self.fixture(root)), contextlib.redirect_stdout(io.StringIO()):
                export_translation.main()
            row=json.loads((root/"out/translated.json").read_text())["segments"][0]
            self.assertEqual((row["start"],row["end"]),(0.,1.))
            self.assertFalse(row["tts_timing_verified"])
            unit=json.loads((root/"out/speech-units.draft.json").read_text())["units"][0]
            self.assertFalse(unit["grouping_verified"])


if __name__ == "__main__":
    unittest.main()
