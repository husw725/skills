import unittest
from repair_episode_feedback import validate_config, request_for, TARGETS


class FeedbackRepairTests(unittest.TestCase):
    def config(self):
        return {'base_report': 'output/drama-01/episode-02/cartesia-v2-pilot/render-report.json',
                'output_dir': 'output/drama-01/episode-02/feedback-v3',
                'voice_bank': 'output/drama-01/voice-bank.json',
                'screenplay_context': 'output/drama-01/episode-02/editorial/screenplay-context.json',
                'episode': 2, 'project_id': 59, 'review_project_id': 148, 'old_review_asset_id': 2478,
                'voice_role': 'Laura', 'patches': {k: {'cue_ids': v, 'emotion': 'fearful', 'speed': 1.0,
                'synthesis_text': 'test phonetic input'} for k, v in TARGETS.items()}}

    def test_v2_output_and_other_voice_bank_refused(self):
        cfg = self.config()
        validate_config(cfg)
        for k, v in [('output_dir', 'output/drama-01/episode-02/cartesia-v2-pilot'),
                     ('voice_bank', 'output/drama-01/new-bank.json')]:
            with self.assertRaises(ValueError):
                validate_config({**cfg, k: v})

    def test_cannot_patch_other_cue_or_role(self):
        for key, value in [('patches', {}), ('voice_role', 'Carmilla'), ('old_review_asset_id', 2354)]:
            with self.assertRaises(ValueError):
                validate_config({**self.config(), key: value})

    def test_wrong_backend_voice_refused(self):
        with self.assertRaises(ValueError):
            request_for('test', 'cartesia:example', 59)

    def test_explicit_phonetic_request_separate_from_translation(self):
        text = 'phonetic test input'
        request = request_for(text, 'studio_existing', 59)
        self.assertEqual(request['text'], text)
        self.assertEqual(request['model'], 'speech-2.8-hd')
        self.assertEqual(request['languageBoost'], 'Portuguese')
        self.assertEqual(request['emotion'], 'fearful')
        self.assertIsNone(request['language'])
        self.assertNotIn('referenceAudioList', request)


if __name__ == '__main__':
    unittest.main()
