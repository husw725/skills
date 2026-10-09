import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import translate as tr


class FakeClient:
    model = "test-only-mock"

    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.usage = []

    def complete(self, instruction, data):
        self.calls.append((instruction, data.copy()))
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result


def row(sid="1", text="林薇，别走！", start=0, end=3, episode="1"):
    return {"id": sid, "text": text, "start": start, "end": end, "speaker": "unknown", "episode": episode}


BIBLE = {"target_locale": "pt-BR", "glossary": [
    {"source": "林薇", "target": "Mariana", "kind": "person"},
    {"source": "薇薇", "target": "Mari", "kind": "person"},
], "story_notes": ["林薇和薇薇是同一人"]}


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_quiet(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return tr.translate_rows(*args, **kwargs)

    def test_srt_bom_and_exact_times(self):
        path = self.root / "in.srt"
        path.write_text("\ufeff1\n00:01:02,003 --> 00:01:04,567\n你好\n朋友\n", encoding="utf-8")
        data = tr.load_segments(path)
        self.assertEqual((data[0]["start"], data[0]["end"]), (62.003, 64.567))
        self.assertEqual(data[0]["text"], "你好 朋友")
        self.assertEqual(tr.srt_time(62.003), "00:01:02,003")

    def test_bad_input_times_ids_and_reserved_tokens(self):
        for rows in ([row(end=0)], [row(start=float("nan"))], [row(start=True)],
                     [row(), row()], [row(text="[[G0000]]")]):
            path = self.root / "bad.json"
            tr.save_json(path, rows)
            with self.assertRaises(ValueError):
                tr.load_segments(path)

    def test_glossary_longest_match_and_alias(self):
        bible = {"glossary": [{"source": "陆景川", "target": "Rafael Costa"},
                              {"source": "陆", "target": "Costa"}]}
        glossary = tr.ProtectedGlossary(bible)
        protected = glossary.protect("陆景川来了")
        self.assertEqual(glossary.expand(protected), "Rafael Costa来了")

    def test_latin_name_not_substring(self):
        glossary = tr.ProtectedGlossary({"glossary": [{"source": "Ana", "target": "Ana"}]})
        self.assertEqual(glossary.protect("banana"), "banana")
        self.assertEqual(glossary.expand(glossary.protect("Ana, vem!")), "Ana, vem!")

    def test_token_omission_addition_unknown_and_spelling_rejected(self):
        glossary = tr.ProtectedGlossary(BIBLE)
        source = glossary.protect("林薇，林薇！")
        for bad in ("Vem!", "[[G0000]]!", "[[G9999]] [[G0000]]!", "林薇，林薇！"):
            with self.assertRaises(ValueError):
                glossary.check(source, bad)

    def test_accented_name_not_substring(self):
        glossary = tr.ProtectedGlossary({"glossary": [{"source": "João", "target": "João"}]})
        self.assertEqual(glossary.protect("Joãozinho"), "Joãozinho")
        self.assertEqual(glossary.expand(glossary.protect("João, vem!")), "João, vem!")

    def test_numbers_require_audio_duration_verification(self):
        glossary = tr.ProtectedGlossary(BIBLE)
        source = {**row(text="五百元", end=2), "protected_source": "五百元", "source_duration_s": 2}
        selected = tr.choose_rows({"segments": [{"id": "1", "candidates": ["500 reais."]}]},
                                  [source], glossary, 5, 1)
        self.assertTrue(selected[0]["timing_estimate_uncertain"])
        self.assertTrue(selected[0]["timing_needs_review"])

    def test_locked_name_change_rejected(self):
        with self.assertRaises(ValueError):
            tr.merge_bible(BIBLE, {"glossary": [{"source": "林薇", "target": "Julia"}], "story_notes": []})

    def test_context_flows_between_batches_and_episodes(self):
        rows = [row(), row("2", "薇薇，别走！", episode="2")]
        glossary = tr.ProtectedGlossary(BIBLE)
        token1 = glossary.protect("林薇")
        token2 = glossary.protect("薇薇")
        client = FakeClient([
            {"segments": [{"id": "1", "candidates": [f"{token1}, não vá!"]}]}, {"issues": []},
            {"segments": [{"id": "2", "candidates": [f"{token2}, não vá!"]}]}, {"issues": []},
        ])
        result = self.run_quiet(rows, BIBLE, client, self.root / "translated.json",
                                batch_size=1, tolerance=1, revisions=0)
        self.assertEqual(result["segments"][0]["translation"], "Mariana, não vá!")
        self.assertEqual(result["segments"][1]["translation"], "Mari, não vá!")
        self.assertEqual(client.calls[2][1]["previous_translations"][0]["id"], "1")
        self.assertEqual(client.calls[0][1]["source_context_after"][0]["id"], "2")
        self.assertTrue((self.root / "translated.pt-BR.episode-001.srt").exists())
        self.assertTrue((self.root / "translated.pt-BR.episode-002.srt").exists())
        self.assertFalse(result["segments"][0]["tts_timing_verified"])

    def test_semantic_review_repair_retains_final_feedback(self):
        rows = [row(text="我不是你哥哥。", end=2)]
        client = FakeClient([
            {"segments": [{"id": "1", "candidates": ["Sou seu irmão."]}]},
            {"issues": [{"id": "1", "severity": "error", "reason": "Dropped negation"}]},
            {"segments": [{"id": "1", "candidates": ["Não sou seu irmão."]}]}, {"issues": []},
        ])
        result = self.run_quiet(rows, BIBLE, client, self.root / "out.json", tolerance=1, revisions=1)
        self.assertEqual(result["segments"][0]["translation"], "Não sou seu irmão.")
        self.assertIn("Dropped negation", str(client.calls[2][1]["review_feedback"]))

    def test_unresolved_semantic_and_timing_issues_are_reported(self):
        client = FakeClient([
            {"segments": [{"id": "1", "candidates": ["Eu nunca abandonaria você nessa situação."]}]},
            {"issues": [{"id": "1", "severity": "warning", "reason": "Ambiguous referent"}]},
        ])
        result = self.run_quiet([row(text="别走", end=0.3)], BIBLE, client,
                                self.root / "out.json", revisions=0)
        self.assertEqual(result["review_required_count"], 1)
        self.assertTrue(result["segments"][0]["timing_needs_review"])
        self.assertFalse(result["segments"][0]["tts_timing_verified"])
        self.assertEqual(tr.read_json(self.root / "out.review.json")["segments"][0]["id"], "1")

    def test_candidate_choice_accounts_for_expanded_names(self):
        glossary = tr.ProtectedGlossary(BIBLE)
        source = {**row(), "protected_source": glossary.protect("林薇，别走！"), "source_duration_s": 1.5}
        token = glossary.protect("林薇")
        reply = {"segments": [{"id": "1", "candidates": [f"{token}, por favor, não vá embora agora!", f"{token}, fica!"]}]}
        selected = tr.choose_rows(reply, [source], glossary, 5, 0.2)
        self.assertEqual(selected[0]["translation"], "Mariana, fica!")

    def test_resume_does_not_repeat_completed_api_work(self):
        rows = [row("1", "别走"), row("2", "我知道")]
        output = self.root / "out.json"
        client = FakeClient([
            {"segments": [{"id": "1", "candidates": ["Não vá!"]}]}, {"issues": []},
            RuntimeError("network interrupted"),
        ])
        with self.assertRaises(RuntimeError):
            self.run_quiet(rows, BIBLE, client, output, batch_size=1, tolerance=1, revisions=0)
        self.assertEqual(len(tr.read_json(str(output) + ".checkpoint.json")["segments"]), 1)
        resumed = FakeClient([{ "segments": [{"id": "2", "candidates": ["Eu sei."]}]}, {"issues": []}])
        result = self.run_quiet(rows, BIBLE, resumed, output, batch_size=1, tolerance=1, revisions=0)
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(resumed.calls[0][1]["requested_segments"][0]["id"], "2")
        self.assertEqual(resumed.calls[0][1]["previous_translations"][0]["id"], "1")
        changed = {**BIBLE, "glossary": [{"source": "林薇", "target": "Julia"}]}
        with self.assertRaises(ValueError):
            self.run_quiet(rows, changed, FakeClient([]), output, batch_size=1, tolerance=1, revisions=0)

    def test_preparation_finalization_and_resume_preserve_user_names(self):
        bible_path = self.root / "bible.json"
        overrides = {"glossary": BIBLE["glossary"], "story_notes": []}
        replies = [{"glossary": [], "story_notes": ["Same person"]},
                   {"glossary": BIBLE["glossary"], "story_notes": ["Same person"]}]
        with contextlib.redirect_stdout(io.StringIO()):
            bible = tr.prepare_bible([row()], FakeClient(replies), bible_path, overrides)
            saved = tr.prepare_bible([row()], FakeClient([]), bible_path, overrides)
        self.assertEqual(bible, saved)
        self.assertEqual(tr.validate_bible(saved)["林薇"], "Mariana")

    def test_finalization_cannot_drop_or_change_user_names(self):
        client = FakeClient([
            {"glossary": [], "story_notes": []},
            {"glossary": [{"source": "林薇", "target": "Julia"}, BIBLE["glossary"][1]], "story_notes": []},
        ])
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            tr.prepare_bible([row()], client, self.root / "bible.json", BIBLE)

    def test_changed_ids_and_chinese_output_rejected(self):
        glossary = tr.ProtectedGlossary(BIBLE)
        source = {**row(text="你好"), "protected_source": "你好", "source_duration_s": 3}
        for reply in ({"segments": [{"id": "2", "candidates": ["Olá."]}]},
                      {"segments": [{"id": "1", "candidates": ["你好"]}]}):
            with self.assertRaises(ValueError):
                tr.choose_rows(reply, [source], glossary, 5, 0.2)

    def test_dry_run_never_calls_api_or_writes_outputs(self):
        path = self.root / "in.json"
        tr.save_json(path, [row()])
        with contextlib.redirect_stdout(io.StringIO()), patch.object(tr.MiniMax, "complete") as call:
            self.assertEqual(tr.main([str(path), "--dry-run", "--subtitle-only", "--output-dir", str(self.root / "no-output")]), 0)
        call.assert_not_called()
        self.assertFalse((self.root / "no-output").exists())

    def test_input_overwrite_rejected(self):
        path = self.root / "translated.json"
        tr.save_json(path, [row()])
        with self.assertRaises(ValueError):
            tr.main([str(path), "--dry-run", "--subtitle-only", "--output-dir", str(self.root)])


class ApiTests(unittest.TestCase):
    def response(self, result):
        response = io.StringIO(json.dumps(result))
        return response

    def test_real_request_shape_and_fenced_json_response(self):
        client = tr.MiniMax("test-secret")
        result = {"choices": [{"finish_reason": "stop", "message": {"content": '```json\n{"issues": []}\n```'}}],
                  "usage": {"total_tokens": 4}}
        with patch.object(tr.urllib.request, "urlopen", return_value=self.response(result)) as request:
            self.assertEqual(client.complete("review", {}), {"issues": []})
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["model"], "MiniMax-M2.7")
        self.assertIn("max_completion_tokens", payload)
        self.assertEqual(len(client.usage), 1)

    def test_rate_limit_retry_and_no_retry_auth_failure(self):
        error = urllib.error.HTTPError("https://example.test", 429, "rate limit", {}, None)
        result = {"choices": [{"message": {"content": '{"issues": []}'}}]}
        with patch.object(tr.urllib.request, "urlopen", side_effect=[error, self.response(result)]) as request, \
                patch.object(tr.time, "sleep"):
            tr.MiniMax("secret").complete("", {})
            self.assertEqual(request.call_count, 2)
        auth = urllib.error.HTTPError("https://example.test", 401, "secret", {}, None)
        with patch.object(tr.urllib.request, "urlopen", side_effect=auth) as request:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as failure:
                tr.MiniMax("secret").complete("", {})
            self.assertNotIn("secret", str(failure.exception))
            self.assertEqual(request.call_count, 1)

    def test_truncated_or_invalid_json_is_not_accepted(self):
        for response in ({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
                         {"choices": [{"message": {"content": "not JSON"}}]}):
            with patch.object(tr.urllib.request, "urlopen", return_value=self.response(response)):
                with self.assertRaises(RuntimeError):
                    tr.MiniMax("secret").complete("", {})


if __name__ == "__main__":
    unittest.main()
