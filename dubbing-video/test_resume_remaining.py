import copy
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
    def test_neighbor_retry_requires_exact_failure_and_no_existing_render(self):
        from resume_carmilla_neighbor import retry_root
        with TemporaryDirectory() as temp:
            root=Path(temp)
            record={'episodes':{'20':{'stage':'requires_review','detail':'Unknown readers cannot be inferred identical from voice casting'}}}
            save_json(root/'season-progress.json',record)
            self.assertEqual(retry_root(root),season.NEIGHBOR2_ROOT)
            record['episodes']['20']['detail']='Unresolved source reading'
            save_json(root/'season-progress.json',record)
            with self.assertRaises(ValueError):retry_root(root)
            record['episodes']['20']['detail']='Unknown readers cannot be inferred identical from voice casting'
            save_json(root/'season-progress.json',record)
            save_json(root/'episode-20/render-report.json',{})
            with self.assertRaises(ValueError):retry_root(root)

    def neighbor_fixture(self):
        row={'id':'e20-9','episode':'20','start':19.966,'end':21.3,'text':'I will hurt you'}
        following={'id':'e20-10','episode':'20','start':21.3,'end':23.033,'text':'you will hate me.'}
        words=[{'word':w,'start':a,'end':b,'probability':.95} for w,a,b in [
            ('I',20.05,20.43),('will',20.43,20.61),('hurt',20.61,20.91),('you',20.91,21.15),
            ('You',21.29,21.33),('will',21.33,21.49),('hate',21.49,21.81),('me',21.81,22.15)]]
        models={name:{'segments':[{'words':copy.deepcopy(words)}],'baseline_segments':[{'words':copy.deepcopy(words)}],
            'method':'raw-neighbor'} for name in ('small.en','medium.en')}
        ev={'e20-9':{'cue':row,'next_source_cue':following,'models':models}}
        review={'cues':[{'id':'e20-9','source_reading_status':'subtitle_confirmed',
            'source_audio_reading':'I will hurt you','source_reading_evidence':'Complete next source sentence independently assigned.'}]}
        return review,[row],ev

    def test_neighbor_repair_requires_the_entire_actual_next_sentence(self):
        review,rows,ev=self.neighbor_fixture()
        self.assertIn('e20-9',season.validate_source_readings(review,rows,ev))
        for mode in ('context','tight'):
            review,rows,ev=self.neighbor_fixture()
            for m in ev['e20-9']['models'].values():m['method']=mode
            with self.assertRaises(ValueError):season.validate_source_readings(review,rows,ev)
        review,rows,ev=self.neighbor_fixture()
        ev['e20-9']['next_source_cue']['text']='you will love me'
        with self.assertRaises(ValueError):season.validate_source_readings(review,rows,ev)
        review,rows,ev=self.neighbor_fixture()
        ev['e20-9']['models']['medium.en']['segments'][0]['words'].pop()
        with self.assertRaises(ValueError):season.validate_source_readings(review,rows,ev)

    def test_neighbor_repair_never_omits_current_negation_or_low_confidence(self):
        review,rows,ev=self.neighbor_fixture()
        for m in ev['e20-9']['models'].values():
            m['segments'][0]['words'].insert(0,{'word':'not','start':19.98,'end':20.04,'probability':.99})
        with self.assertRaises(ValueError):season.validate_source_readings(review,rows,ev)
        review,rows,ev=self.neighbor_fixture()
        for m in ev['e20-9']['models'].values():m['segments'][0]['words'][-1]['probability']=.2
        with self.assertRaises(ValueError):season.validate_source_readings(review,rows,ev)

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
