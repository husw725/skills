from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from types import SimpleNamespace
import contextlib,json,os
from translate import read_json,save_json
from dub_episode import digest,RATE

import rerun_carmilla_season as season
from repair_carmilla_measured import selected_pending
from cartesia_pilot import bind


@contextlib.contextmanager
def in_directory(path):
    previous=Path.cwd();os.chdir(path)
    try:yield
    finally:os.chdir(previous)


class MeasuredRepairTests(TestCase):
    def test_only_measured_failures_and_never_completed_or_source_errors(self):
        error='Measured speech too long: revise faithfully; no automatic paid speed retries'
        baseline={'episodes':{
            '9':{'stage':'requires_review','detail':error},
            '10':{'stage':'requires_review','detail':'Unresolved textual/source error; no synthesis permitted'},
            '11':{'stage':'requires_review','detail':error},
            '12':{'stage':'requires_review','detail':error},
            '15':{'stage':'rendered_candidate','detail':error}}}
        state={'episodes':{'11':{'stage':'rendered_candidate'}}}
        self.assertEqual(selected_pending(baseline,state),[9])

    def test_final_cache_reuses_same_request_and_blocks_ambiguous_prior(self):
        with TemporaryDirectory() as temp:
            final=Path(temp);folder=final/'episode-09/utterances/a';folder.mkdir(parents=True)
            req={'text':'Saved utterance','speed':1,'voiceId':'existing'};bind(folder/'request-fingerprint.json',req)
            with patch.object(season,'FINAL_ROOT',final):
                self.assertEqual(season.paid_audio_folder(9,req,final/'target',final),folder)
                pending=folder/'submission.private.submission-pending.json';pending.write_text('{}')
                with self.assertRaises(ValueError):season.paid_audio_folder(9,{'text':'Different text'},final/'target',final)

    def test_regroup_advice_keeps_speaker_voice_emotion_and_gap_boundaries(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);ep=root/'episode-09';ep.mkdir()
            units=[]
            for i in range(2):
                audio=ep/'utterances'/str(i);audio.mkdir(parents=True);wav=audio/'original.wav';wav.write_bytes(b'audio')
                save_json(audio/'audio-receipt.json',{'sha256':digest(wav)})
                units.append({'id':str(i),'cue_ids':[str(i)],'start':i*.6,'end':i*.6+.5,
                    'translation':'Text','source_speaker':'Father','production_voice':'Father','emotion':'calm'})
            plan={'assets':{'video':'video'},'units':units}
            save_json(ep/'plan.json',plan);bind(ep/'reviewed-plan-fingerprint.json',plan)
            args=SimpleNamespace(prior_root=root,finalize_pending=True,ffmpeg=Path('ffmpeg'))
            with patch.object(season,'TIMING_ROOT',root),patch.object(season,'BASE_ROOT',root/'base'), \
                 patch.object(season,'probe',return_value={'format':{'duration':'5'}}), \
                 patch.object(season,'read_audio',return_value=[]), \
                 patch.object(season,'trim_edges',return_value=([0]*(3*RATE),0,0)):
                self.assertEqual(season.revision_feedback(9,args)['regroup_candidates'][0]['cue_ids'],['0','1'])
                for field,value in [('source_speaker','unknown'),('production_voice','Laura'),('emotion','sad'),('start',1.5)]:
                    changed=json.loads(json.dumps(plan));changed['units'][1][field]=value
                    save_json(ep/'plan.json',changed);(ep/'reviewed-plan-fingerprint.json').unlink();bind(ep/'reviewed-plan-fingerprint.json',changed)
                    self.assertEqual(season.revision_feedback(9,args)['regroup_candidates'],[])

    def test_context_evidence_binds_original_audio_and_rejects_other_episode_transcript(self):
        with TemporaryDirectory() as temp,in_directory(temp):
            source=Path('original.wav');source.write_bytes(b'original');prior=Path('prior/episode-04');prior.mkdir(parents=True)
            save_json(prior/'reviewed.json',{'cues':[{'id':'x','issues':[{'severity':'error'}]}]})
            row={'id':'x','text':'Example','start':1.,'end':2.}
            folder=Path('output/carmilla-source-verification-20261017/episode-04/x');folder.mkdir(parents=True)
            clip=folder/'original-context.wav';clip.write_bytes(b'clip')
            for model in ['small.en','medium.en']:
                original={'cue':row,'model':model,'source_audio_sha256':digest(source),'clip_sha256':digest(clip),'model_files':{}}
                full=folder.parent/(model+'.context-full.json')
                spec={**original,'method':'unprompted-full-episode-vad-v1','decoding':{'vad_filter':True}}
                save_json(folder/(model+'.json'),{'input':original,'segments':[]})
                save_json(full,{'input':spec,'segments':[]})
                save_json(folder/(model+'.context.json'),{'input':{**spec,'whole_episode_evidence':str(full),
                    'whole_episode_sha256':digest(full)},'segments':[]})
            _,inputs=season.source_audio_evidence(4,[row],source,Path('prior'))
            self.assertEqual(inputs[str(source)],digest(source))
            full=folder.parent/'small.en.context-full.json';record=read_json(full)
            record['input']['source_audio_sha256']='other-episode';save_json(full,record)
            context=folder/'small.en.context.json';record=read_json(context)
            record['input']['whole_episode_sha256']=digest(full);save_json(context,record)
            with self.assertRaises(ValueError):season.source_audio_evidence(4,[row],source,Path('prior'))

    def test_fitting_tests_approved_ceiling_before_rejecting_frame_padding(self):
        with patch.object(season,'run') as run,patch.object(season,'read_audio',side_effect=[[0]*103,[0]*99]):
            audio,factor=season.fit_speech(Path('trim'),Path('fit'),100/RATE,1.19,Path('ffmpeg'))
            self.assertEqual(factor,1.2);self.assertEqual(len(audio),99)
            self.assertEqual(run.call_count,2)

        with patch.object(season,'run') as run,patch.object(season,'read_audio',return_value=[0]*103):
            with self.assertRaises(ValueError):season.fit_speech(Path('trim'),Path('fit'),100/RATE,1.19,Path('ffmpeg'))
            self.assertEqual(run.call_count,2)

    def test_tight_evidence_requires_clip_binding_and_exact_source_not_context_fallback(self):
        with TemporaryDirectory() as temp,in_directory(temp):
            source=Path('source.wav');source.write_bytes(b'source')
            prior=Path('prior/episode-06');prior.mkdir(parents=True)
            review=prior/'reviewed.json';save_json(review,{'cues':[{'id':'x','issues':[{'severity':'error'}]}]})
            row={'id':'x','start':1.,'end':2.,'text':'Original'}
            folder=Path('output/carmilla-source-verification-20261017/episode-06/x');folder.mkdir(parents=True)
            clip=folder/'original-context.wav';clip.write_bytes(b'original clip')
            tight_folder=Path('output/carmilla-source-tight-20261017/episode-06/x');tight_folder.mkdir(parents=True)
            tight_clip=tight_folder/'original-tight.wav';tight_clip.write_bytes(b'tight clip')
            clip_spec={'source_audio_sha256':digest(source),'start':.85,'end':2.15,
                'decoding':{'channels':1,'sample_rate':16000,'codec':'pcm_s16le'}}
            bind(tight_folder/'clip-input.json',clip_spec)
            words=[{'word':'Who','start':1.,'end':1.5,'probability':.9}]
            segments=[{'words':words}]
            for model in ('small.en','medium.en'):
                original={'cue':row,'model':model,'source_audio_sha256':digest(source),
                    'clip_sha256':digest(clip),'model_files':{}}
                save_json(folder/(model+'.json'),{'input':original,'segments':segments})
                full=folder.parent/(model+'.context-full.json')
                spec={**original,'method':'unprompted-full-episode-vad-v1','decoding':{'vad_filter':True}}
                save_json(full,{'input':spec,'segments':[]})
                save_json(folder/(model+'.context.json'),{'input':{**spec,'whole_episode_evidence':str(full),
                    'whole_episode_sha256':digest(full)},'segments':[]})
                tight={**original,'method':'unprompted-cue-tight-v1','clip_sha256':digest(tight_clip),
                    'source_review_sha256':digest(review),'padding_seconds':.15,'clip_start':.85,'clip_end':2.15,
                    'decoding':{'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':False,
                        'word_timestamps':True,'vad_filter':False}}
                save_json(tight_folder/(model+'.json'),{'input':tight,'segments':segments})
            evidence,inputs=season.source_audio_evidence(6,[row],source,Path('prior'),mode='tight')
            self.assertEqual(evidence['x']['models']['small.en']['segments'],segments)
            self.assertIn(str(tight_clip),inputs)
            tight_clip.write_bytes(b'changed source clip')
            with self.assertRaisesRegex(ValueError,'Tight source evidence'):
                season.source_audio_evidence(6,[row],source,Path('prior'),mode='tight')

    def measure_fixture(self,root):
        bank=Path('output/drama-01');(bank/'cartesia-pilot-voices').mkdir(parents=True)
        save_json(bank/'cartesia-pilot-voices/voice-bank.json',{r:{'voice_id':'cartesia:saved-'+r} for r in ['Laura','Carmilla']})
        save_json(bank/'voice-bank.json',{'voices':{r:{'voice_id':'saved-'+r} for r in season.ROLES}})
        ep=root/'episode-09';ep.mkdir(parents=True)
        source=Path('video.mp4');source.write_bytes(b'fixture')
        for name in ['screenplay-context.json','reviewed.json','Carmilla_EP09_pt-BR_revised.srt']:(ep/name).write_bytes(b'fixture')
        plan={'episode':9,'project_id':59,'blocking_issues':[],'input_sha256':{},'assets':{'video':str(source)},
            'reviewed_context_sha256':digest(ep/'screenplay-context.json'),'reviewed_response_sha256':digest(ep/'reviewed.json'),
            'translation_srt_sha256':digest(ep/'Carmilla_EP09_pt-BR_revised.srt'),
            'units':[{'id':str(i),'cue_ids':[str(i)],'start':i,'end':i+.4,'production_voice':'Laura',
                      'translation':'Keep every word.','emotion':'calm'} for i in range(2)]}
        save_json(ep/'plan.json',plan);bind(ep/'reviewed-plan-fingerprint.json',plan)
        return ep

    def test_measurement_collects_every_unit_even_if_first_is_too_long_and_never_renders(self):
        with TemporaryDirectory() as temp,in_directory(temp):
            root=Path('attempt');ep=self.measure_fixture(root)
            def generate(client,req,target):
                target.mkdir(parents=True,exist_ok=True);wav=target/'original.wav';wav.write_bytes(b'paid fixture')
                save_json(target/'audio-receipt.json',{'sha256':digest(wav)})
                return wav,{'task_id':1}
            args=SimpleNamespace(measure_only=True,finalize_pending=True,prior_root=None,cache_roots=[],mcp_config=Path('cfg'),ffmpeg=Path('ffmpeg'))
            with patch.object(season,'ROOT',root),patch.object(season,'Mflix'), \
                 patch.object(season,'probe',return_value={'format':{'duration':'10'}}), \
                 patch.object(season,'generate',side_effect=generate) as paid, \
                 patch.object(season,'read_audio',return_value=[]), \
                 patch.object(season,'trim_edges',return_value=([0]*(3*RATE),0,0)):
                season.render(9,args)
            result=read_json(ep/'duration-measurements.json')
            self.assertTrue(result['complete']);self.assertEqual(paid.call_count,2)
            self.assertTrue(all(g['requires_shortening'] for g in result['groups']))
            self.assertFalse((ep/'render-report.json').exists())


if __name__=='__main__':main()
