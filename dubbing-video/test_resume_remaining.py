from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch

from cartesia_pilot import bind
from dub_episode import RATE
from translate import save_json
import rerun_carmilla_season as season
from resume_carmilla_remaining import selected


class ResumeTests(TestCase):
    def test_prior_timing2_cache_reused_and_ambiguous_changed_request_blocks(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);old=root/'episode-10/utterances/old';old.mkdir(parents=True)
            req={'text':'existing exact words','voice':'frozen','speed':1}
            bind(old/'request-fingerprint.json',req)
            with patch.object(season,'TIMING2_ROOT',root):
                self.assertEqual(season.paid_audio_folder(10,req,root/'new',root),old)
                (old/'submission.private.submission-pending.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'Ambiguous'):
                    season.paid_audio_folder(10,{'text':'revised words'},root/'new',root)

    def test_selects_only_timing_errors_and_skips_completed(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            save_json(root/'season-progress.json',{'episodes':{
                '10':{'stage':'requires_review','detail':'Cannot fit without truncating/over-speeding'},
                '18':{'stage':'requires_review','detail':'Unresolved source reading; no synthesis'},
                '22':{'stage':'requires_review','detail':'Cannot fit without truncating/over-speeding'}}})
            self.assertEqual(selected({10:root,18:root,22:root},{'episodes':{'22':{'stage':'rendered_candidate'}}}),[10])

    def test_alternate_fitter_uses_same_ceiling_without_trimming(self):
        with patch.object(season,'run') as run,patch.object(season,'read_audio',side_effect=[[0]*103,[0]*100]):
            audio,factor=season.fit_speech(Path('trim'),Path('fit'),100/RATE,1.2,Path('ffmpeg'),True)
            self.assertEqual(len(audio),100);self.assertEqual(factor,1.2)
            self.assertEqual(run.call_args.args[0][7],'rubberband=tempo=1.2')
            self.assertFalse(any('atrim' in str(x) for call in run.call_args_list for x in call.args[0]))
        with patch.object(season,'run'),patch.object(season,'read_audio',return_value=[0]*103):
            with self.assertRaisesRegex(ValueError,'Cannot fit'):
                season.fit_speech(Path('trim'),Path('fit'),100/RATE,1.2,Path('ffmpeg'),True)


if __name__=='__main__':main()
