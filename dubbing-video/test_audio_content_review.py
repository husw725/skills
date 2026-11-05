"""Synthetic network mocks; never calls a real API."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from audio_content_review import analyze


class AudioAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.wav = self.root/'input.wav';self.wav.write_bytes(b'synthetic input')
        self.item = {'id': 'one', 'prompt': 'Identify speech or music.', 'audio': [
            {'label': 'source', 'path': str(self.wav), 'sha256': hashlib.sha256(self.wav.read_bytes()).hexdigest()}]}
        obj = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(
            {'files': [{'label': 'source', 'observations': [], 'uncertainties': ['synthetic fixture']} ]})}]}}]}
        self.http = Mock();self.http.post.return_value.status_code=200;self.http.post.return_value.json.return_value=obj
        self.env = patch.dict(os.environ, {'GEMINI_API_KEY': 'synthetic-only'});self.env.start();self.addCleanup(self.env.stop)

    def run_analysis(self):
        return analyze(self.item, 'gemini-2.5-flash', self.root/'out', self.http)

    def test_success_reuses_response_without_post(self):
        self.assertFalse(self.run_analysis()['native_listening_passed'])
        self.assertEqual(self.run_analysis()['status'], 'machine_analysis_complete')
        self.assertEqual(self.http.post.call_count, 1)

    def test_unknown_submission_never_retried(self):
        self.http.post.side_effect=TimeoutError()
        with self.assertRaisesRegex(RuntimeError, 'unknown'): self.run_analysis()
        with self.assertRaisesRegex(ValueError, 'unresolved'): self.run_analysis()
        self.assertEqual(self.http.post.call_count,1)

    def test_changed_bytes_blocked_before_network(self):
        self.wav.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA'): self.run_analysis()
        self.http.post.assert_not_called()

    def test_changed_prompt_does_not_overwrite_attempt(self):
        self.run_analysis();self.item['prompt']='different task'
        with self.assertRaisesRegex(ValueError,'inputs changed'): self.run_analysis()
        self.assertEqual(self.http.post.call_count,1)

    def test_rejected_request_does_not_retry(self):
        self.http.post.return_value.status_code=429
        with self.assertRaisesRegex(RuntimeError,'429'): self.run_analysis()
        with self.assertRaisesRegex(ValueError,'rejected'): self.run_analysis()
        self.assertEqual(self.http.post.call_count,1)

    def test_bad_output_retained_without_new_post(self):
        self.http.post.return_value.json.return_value={'candidates':[]}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'Incomplete'): self.run_analysis()
        self.assertEqual(self.http.post.call_count,1)

    def test_token_limit_retains_paid_response_without_retry(self):
        self.http.post.return_value.json.return_value = {'candidates': [{'finishReason': 'MAX_TOKENS'}]}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'Incomplete'): self.run_analysis()
        self.assertEqual(self.http.post.call_count, 1)
        request = self.http.post.call_args.kwargs['json']
        self.assertEqual(request['generationConfig']['thinkingConfig']['thinkingBudget'], 0)

    def test_response_tamper_rejected(self):
        self.run_analysis();(self.root/'out/one/response.private.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'response changed'): self.run_analysis()
        self.assertEqual(self.http.post.call_count,1)


if __name__ == '__main__':unittest.main()
