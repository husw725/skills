import unittest
from diagnostic_review_episodes import spoken_words, validate_config


class DiagnosticReviewTests(unittest.TestCase):
    def config(self, n):
        ep = {k: f'output/drama-01/episode-{n:02}/{v}' for k, v in {
            'original_plan': 'dub-plan-v1.json', 'source_subtitles': 'editorial/source.json',
            'screenplay_context': 'editorial/screenplay-context.json', 'base_report': 'dub-v1/render-report.json',
            'subtitles': 'translation/translated.pt-BR.srt', 'output_dir': 'diagnostic-v2'}.items()}
        ep.update({'old_review_asset_id': {7:2359,29:2381}[n],
                   'reuse_groups': [] if n==7 else ['e29-utterance-008']})
        return {'project_id': 59, 'review_project_id': 148, 'cloning_enabled': False, 'episodes': {str(n):ep}}

    def test_only_requested_episodes_and_no_cloning(self):
        for n in (7,29):
            c = self.config(n); validate_config(c,n)
            with self.assertRaises(ValueError):validate_config({**c,'cloning_enabled': True},n)
        with self.assertRaises(ValueError):validate_config({},13)

    def test_refuses_writing_into_original_episode(self):
        c=self.config(7);c['episodes']['7']['output_dir']='output/drama-01/episode-07/dub-v1'
        with self.assertRaises(ValueError):validate_config(c,7)

    def test_uncertain_source_reuse_scope_cannot_expand(self):
        c=self.config(29);c['episodes']['29']['reuse_groups']=['e29-utterance-018']
        with self.assertRaises(ValueError):validate_config(c,29)

    def test_synthesis_punctuation_can_change_but_negation_cannot(self):
        self.assertEqual(spoken_words('A mesma marca... no pescoço dela.'),spoken_words('A mesma marca no pescoço dela.'))
        self.assertEqual(spoken_words('Camila!'),spoken_words('CAMILA!'))
        self.assertNotEqual(spoken_words('Não é seguro.'),spoken_words('É seguro.'))
        self.assertNotEqual(spoken_words('todos vocês esta noite'),spoken_words('vocês hoje'))


if __name__=='__main__':unittest.main()
