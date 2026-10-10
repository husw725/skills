import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from codex_translate_episode import call_codex,validate_response


class CodexEditorialTests(unittest.TestCase):
    def response(self):
        return {'matched_main_dialogue':True,'cues':[{'id':'u1','translation':'Oi.','speaker':'Laura',
                'script_evidence':'Laura speaks in matched scene','review_issues':[]}]}

    def test_rejects_missing_or_reordered_cues_and_unmatched_script(self):
        with self.assertRaises(ValueError):validate_response(self.response(),[{'id':'u2'}])
        data=self.response();data['matched_main_dialogue']=False
        with self.assertRaises(ValueError):validate_response(data,[{'id':'u1'}])

    def test_unresolved_error_is_not_published(self):
        data=self.response();data['cues'][0]['review_issues']=[{'severity':'error','reason':'wrong cut'}]
        with self.assertRaises(ValueError):validate_response(data,[{'id':'u1'}])

    def test_first_pass_error_can_reach_review_but_not_production(self):
        data=self.response();data['cues'][0]['review_issues']=[{'severity':'error','reason':'uncertain vocative'}]
        validate_response(data,[{'id':'u1'}],allow_errors=True)
        with self.assertRaises(ValueError):validate_response(data,[{'id':'u1'}])

    def test_codex_prompt_is_stdin_and_failed_run_stops(self):
        with tempfile.TemporaryDirectory() as tmp,patch('codex_translate_episode.subprocess.run') as run:
            run.return_value.returncode=1
            with self.assertRaises(RuntimeError):
                call_codex(Path('codex.exe'),'fixture task',Path('schema.json'),Path('response.json'),Path(tmp)/'log')
            self.assertEqual(run.call_args.kwargs['input'],'fixture task')
            args=run.call_args.args[0]
            self.assertIn('read-only',args);self.assertNotIn('fixture task',args)
