import json
from pathlib import Path
import tempfile
import unittest
from cartesia_pilot import bind, grouped_units, speech_request
from dub_episode import safe_submit


class CartesiaPilotTests(unittest.TestCase):
    def test_input_change_refuses_reusing_paid_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'signature.json'
            bind(p, {'voice_id': 'cartesia:a', 'text': 'Quinze anos.'})
            with self.assertRaises(ValueError):
                bind(p, {'voice_id': 'cartesia:b', 'text': 'Quinze anos.'})

    def test_ambiguous_clone_cannot_resubmit(self):
        class Client:
            calls = 0
            def call(self, *args):
                self.calls += 1
                raise RuntimeError('timeout')
        client = Client()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'clone.private.json'
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    safe_submit(client, 'uploadVoice', {'request': {'platform': 'cartesia'}}, p)
            self.assertEqual(client.calls, 1)

    def test_completed_clone_reuses_receipt(self):
        class Client:
            calls = 0
            def call(self, *args):
                self.calls += 1
                return {'voiceId': 'cartesia:existing'}
        client = Client()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'clone.private.json'
            a = safe_submit(client, 'uploadVoice', {}, p)
            b = safe_submit(client, 'uploadVoice', {}, p)
            self.assertEqual(a, b)
            self.assertEqual(client.calls, 1)

    def test_grouping_rejects_cross_speaker_and_missing_cue(self):
        rows = [{'id': 'a', 'cue_ids': ['1'], 'production_voice': 'Laura', 'start': 0,
                 'end': 1, 'translation': 'Por quê?', 'emotion': 'fearful'},
                {'id': 'b', 'cue_ids': ['2'], 'production_voice': 'Carmilla', 'start': 2,
                 'end': 3, 'translation': 'Confia em mim.', 'emotion': 'whisper'}]
        for groups in [[['a', 'b']], [['a']], [['a'], ['a'], ['b']]]:
            with self.assertRaises(ValueError):
                grouped_units({'units': rows}, groups)

    def test_request_uses_cartesia_locale_without_minimax_emotion(self):
        d = speech_request('Quinze anos.', 'cartesia:existing', 59)
        self.assertEqual(d['language'], 'pt-BR')
        self.assertEqual(d['model'], 'sonic-3.6')
        self.assertIsNone(d['emotion'])
        self.assertNotIn('referenceAudioList', d)
        with self.assertRaises(ValueError):
            speech_request('Quinze anos.', 'studio_minimax', 59)


if __name__ == '__main__':
    unittest.main()
