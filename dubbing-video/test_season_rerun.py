import copy
import json
from pathlib import Path
import tempfile
import unittest
from rerun_carmilla_season import request, validate_editorial, validate_reviewed_plan, storyboard_reference, paid_audio_folder, revision_feedback, speech_window, validate_source_readings
from unittest.mock import patch
from types import SimpleNamespace
from dub_episode import digest, RATE
from translate import save_json,read_json
import rerun_carmilla_season as season
from cartesia_pilot import bind


class SeasonRerunTests(unittest.TestCase):
    def example(self):
        rows=[{'id':'a','text':'Laura','start':0,'end':1},{'id':'b','text':'is here','start':1.1,'end':2}]
        old={c:{'id':c,'production_voice':'Laura'} for c in ('a','b')}
        annotations={c:{'speaker':'Laura'} for c in ('a','b')}
        data={'cues':[{'id':'a','translation':'Laura','emotion':'calm','script_evidence':'Matched Laura scene'},
                      {'id':'b','translation':'chegou.','emotion':'calm','script_evidence':'Matched Laura scene'}],
              'groups':[['a','b']]}
        return data,rows,old,annotations,{'Laura':'Laura'}

    def test_full_coverage_and_locked_name(self):
        args=self.example();validate_editorial(*args)
        data=copy.deepcopy(args[0]);data['groups']=[['a'],['a']]
        with self.assertRaises(ValueError):validate_editorial(data,*args[1:])
        data=copy.deepcopy(args[0]);data['cues'][0]['translation']='Maria'
        with self.assertRaises(ValueError):validate_editorial(data,*args[1:])

    def test_no_cross_speaker_or_unknown_reader_grouping(self):
        args=list(self.example());args[3]['b']['speaker']='Carmilla'
        with self.assertRaises(ValueError):validate_editorial(*args)
        args=list(self.example())
        for c in args[3]:args[3][c]['speaker']='unknown'
        with self.assertRaises(ValueError):validate_editorial(*args)
        args[2]['b']['id']='a'  # an existing, evidence-preserved grouped narrator unit
        validate_editorial(*args)

    def test_no_long_pause_or_emotion_transition_merging(self):
        args=list(self.example());args[1][1]['start']=1.7
        with self.assertRaises(ValueError):validate_editorial(*args)
        args=list(self.example());args[0]['cues'][1]['emotion']='fearful'
        with self.assertRaises(ValueError):validate_editorial(*args)

    def test_gap_at_exact_policy_limit_tolerates_float_roundoff_only(self):
        args=list(self.example());args[1][0]['end']=42.333;args[1][1]['start']=42.933;args[1][1]['end']=43.566
        validate_editorial(*args)
        args[1][1]['start']+=.001
        with self.assertRaises(ValueError):validate_editorial(*args)

    def test_reviewed_gap_policy_still_prohibits_cross_speaker_groups(self):
        args=list(self.example());args[1][1]['start']=1.72
        with self.assertRaises(ValueError):validate_editorial(*args)
        validate_editorial(*args,max_gap=.85)
        args[3]['b']['speaker']='Carmilla'
        with self.assertRaises(ValueError):validate_editorial(*args,max_gap=.85)

    def test_tiny_overflow_may_borrow_silence_but_not_overlap_or_exceed_80ms(self):
        start,target,factor=speech_window(1.87,1.534,44.666,44.0,True)
        self.assertLessEqual(44.666-start,.08);self.assertLessEqual(factor,1.2)
        self.assertGreaterEqual(start,44.1)
        start,target,factor=speech_window(1.87,1.534,44.666,44.64,True)
        self.assertEqual(start,44.666);self.assertGreater(factor,1.2)
        start,target,factor=speech_window(10.,1.,.02,-.1,True)
        self.assertGreaterEqual(start,0.);self.assertGreater(factor,1.2)

    def banks(self):return {'Laura':{'voice_id':'cartesia:saved-laura'}},{'Laura':{'voice_id':'saved-minimax-laura'}}

    def test_fixed_saved_voice_main_dialogue_and_no_spelling_corruption(self):
        u={'production_voice':'Laura','translation':'Não quero morrer.','emotion':'fearful','cue_ids':['x']}
        r,provider=request(u,*self.banks())
        self.assertEqual(provider,'cartesia');self.assertEqual(r['text'],u['translation'])
        self.assertEqual(r['language'],'pt-BR');self.assertEqual(r['speed'],1.)

    def test_ep02_short_cry_phonetics_only_in_synthesis_layer(self):
        u={'production_voice':'Laura','translation':'Não...','emotion':'fearful','cue_ids':['e02-16']}
        r,provider=request(u,*self.banks())
        self.assertEqual(r['voiceId'],'saved-minimax-laura');self.assertEqual(r['emotion'],'fearful')
        self.assertEqual(r['text'],'(gasps)(nɐ̃w̃)!');self.assertEqual(u['translation'],'Não...')
        self.assertEqual(r['speed'],1.);self.assertEqual(r['languageBoost'],'Portuguese')

    def test_missing_or_wrong_backend_voice_has_no_clone_fallback(self):
        u={'production_voice':'Laura','translation':'NÃO!','emotion':'fearful','cue_ids':['e02-18']}
        with self.assertRaises(KeyError):request(u,{}, {})
        with self.assertRaises(ValueError):request(u,{}, {'Laura':{'voice_id':'cartesia:wrong'}})
        with self.assertRaises(ValueError):request({**u,'production_voice':'New Narrator'},{},{})

    def test_unresolved_semantic_error_is_blocking(self):
        args=list(self.example());args[0]['cues'][0]['issues']=[{'severity':'error','reason':'Negation reversed'}]
        with self.assertRaises(ValueError):validate_editorial(*args)
        args[0]['cues'][0]['issues']=[{'severity':'warning','reason':'Native pronunciation listening pending'}]
        validate_editorial(*args)

    def test_unapproved_or_tampered_plan_is_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);plan={'units':[{'translation':'Não.'}]}
            with self.assertRaises(ValueError):validate_reviewed_plan(folder,plan)
            bind(folder/'reviewed-plan-fingerprint.json',plan);validate_reviewed_plan(folder,plan)
            plan['units'][0]['translation']='Sim.'
            with self.assertRaises(ValueError):validate_reviewed_plan(folder,plan)

    def test_storyboard_mapping_is_inline_and_does_not_execute_html(self):
        content='const E='+json.dumps([{'id':'EP-29','script':'wrong episode','storyboard':''},
                                     {'id':'EP-30','script':'<p>Castle surrounded</p>','storyboard':'Threat'}])+'; alert(1);'
        refs=storyboard_reference(29,content)
        self.assertEqual(refs['entries'][0]['storyboard_episode'],'EP-30')
        self.assertIn('Castle surrounded',refs['entries'][0]['script'])

    def test_paid_cache_matches_entire_request_in_same_episode_only(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);old=base/'episode-01/utterances/a';old.mkdir(parents=True)
            req={'voiceId':'saved','text':'Não!','speed':1.0};bind(old/'request-fingerprint.json',req)
            target=base/'new/utterances/b'
            with patch('rerun_carmilla_season.BASE_ROOT',base):
                self.assertEqual(paid_audio_folder(1,req,target,base),old)
                self.assertEqual(paid_audio_folder(2,req,target,base),target)
                for field,value in [('text','Sim!'),('voiceId','different'),('speed',1.1)]:
                    self.assertEqual(paid_audio_folder(1,{**req,field:value},target,base),target)
                with self.assertRaises(ValueError):paid_audio_folder(1,req,target,base/'wrong-root')

    def test_ambiguous_cache_cannot_be_skipped_for_new_payment(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);req={'text':'Não!'};target=base/'new'
            for name in ('a','b'):
                folder=base/'episode-01/utterances'/name;folder.mkdir(parents=True)
                bind(folder/'request-fingerprint.json',req)
            folder=base/'episode-01/utterances/b'
            (folder/'submission.private.submission-pending.json').write_text('{}')
            with patch('rerun_carmilla_season.BASE_ROOT',base):
                with self.assertRaises(ValueError):paid_audio_folder(1,req,target,base)
                with self.assertRaises(ValueError):paid_audio_folder(1,{'text':'new wording'},target,base)
                (folder/'request-fingerprint.json').unlink()
                with self.assertRaises(ValueError):paid_audio_folder(1,{'text':'new wording'},target,base)
                (folder/'submission.private.json').write_text('{"taskId":123}')
                self.assertEqual(paid_audio_folder(1,req,target,base),base/'episode-01/utterances/a')

    def test_measured_feedback_is_bound_to_paid_audio_and_validated_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);ep=base/'episode-01';audio=ep/'utterances/a';audio.mkdir(parents=True)
            wav=audio/'original.wav';wav.write_bytes(b'paid audio fixture')
            (audio/'audio-receipt.json').write_text(json.dumps({'sha256':digest(wav)}))
            plan={'assets':{'video':'source.mp4'},'units':[{'id':'a','cue_ids':['x'],
                  'start':0,'end':1,'translation':'Correct text.'}]}
            (ep/'plan.json').write_text(json.dumps(plan));bind(ep/'reviewed-plan-fingerprint.json',plan)
            args=SimpleNamespace(prior_root=base,ffmpeg=Path('ffmpeg'))
            with patch('rerun_carmilla_season.BASE_ROOT',base), \
                 patch('rerun_carmilla_season.probe',return_value={'format':{'duration':'5'}}), \
                 patch('rerun_carmilla_season.read_audio',return_value=[]), \
                 patch('rerun_carmilla_season.trim_edges',return_value=([0]*3*RATE,0,0)):
                feedback=revision_feedback(1,args)
                self.assertTrue(feedback['measured_groups'][0]['requires_shortening'])
                self.assertAlmostEqual(feedback['measured_groups'][0]['maximum_seconds'],2.16)
                self.assertEqual(feedback['source_sha256'][str(wav)],digest(wav))
                wav.write_bytes(b'changed audio')
                with self.assertRaises(ValueError):revision_feedback(1,args)

    def test_finalize_resume_keeps_completed_and_renders_editorial_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'base';retry=Path(temp)/'retry';final=Path(temp)/'final'
            for root in (base,retry,final):root.mkdir()
            states={str(n):{'stage':'rendered_candidate'} for n in range(1,33)}
            states['9']={'stage':'requires_review'};states['22']={'stage':'requires_review'}
            save_json(base/'season-progress.json',{'episodes':states})
            save_json(retry/'season-progress.json',{'episodes':{'9':states['9'],'22':states['22']}})
            save_json(final/'season-progress.json',{'episodes':{'3':{'stage':'rendered_candidate'},'22':{'stage':'editorial_ready'}}})
            ff=Path(temp)/'ffmpeg';ff.touch()
            argv=['worker','--stage','render','--finalize-pending','--ffmpeg',str(ff),'--mcp-config',str(ff)]
            with patch.multiple(season,BASE_ROOT=base,ROOT=base,RETRY_ROOT=retry,FINAL_ROOT=final), \
                 patch('sys.argv',argv),patch('sys.platform','win32'),patch.object(season,'render') as renderer:
                season.main()
            self.assertEqual([c.args[0] for c in renderer.call_args_list],[9,22])
            state=read_json(final/'season-progress.json')
            self.assertEqual(state['episodes']['3']['stage'],'rendered_candidate')
            self.assertEqual(state['episodes']['22']['stage'],'rendered_candidate')

    def audio_evidence(self):
        row={'id':'x','text':'How many years?','start':1.,'end':2.}
        words=[{'word':'Her','start':1.1,'end':1.3,'probability':.9},
               {'word':'minions.','start':1.3,'end':1.8,'probability':.9}]
        evidence={'x':{'models':{m:{'segments':[{'words':copy.deepcopy(words)}]} for m in ['small.en','medium.en']}}}
        data={'cues':[{'id':'x','source_reading_status':'transcription_corrected',
                       'source_audio_reading':'Her minions.','source_reading_evidence':'Both model word timestamps match the cue.'}]}
        return data,[row],evidence

    def test_source_reading_requires_two_models_and_keeps_original_text(self):
        data,rows,evidence=self.audio_evidence();before=copy.deepcopy(rows)
        result=validate_source_readings(data,rows,evidence)
        self.assertEqual(rows,before);self.assertEqual(result['x']['original_subtitle_text'],'How many years?')
        self.assertFalse(result['x']['human_listened'])
        evidence['x']['models']['medium.en']['segments'][0]['words'][0]['word']='My'
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)

    def test_source_reading_rejects_uncertainty_low_confidence_and_outside_cue(self):
        data,rows,evidence=self.audio_evidence();data['cues'][0]['source_reading_status']='uncertain'
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)
        data,rows,evidence=self.audio_evidence()
        for m in evidence['x']['models'].values():
            for w in m['segments'][0]['words']:w['probability']=.4
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)
        data,rows,evidence=self.audio_evidence()
        for m in evidence['x']['models'].values():
            for w in m['segments'][0]['words']:w['start']+=10;w['end']+=10
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)

    def test_source_reading_cannot_omit_negation_or_low_confidence_core(self):
        for probability in [.9,.1]:
            data,rows,evidence=self.audio_evidence()
            data['cues'][0]['source_audio_reading']='Save him'
            for m in evidence['x']['models'].values():
                m['segments'][0]['words']=[{'word':w,'start':1+i*.2,'end':1.2+i*.2,
                    'probability':probability if w=='not' else .9} for i,w in enumerate(['Do','not','save','him'])]
            with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)

    def test_source_reading_rejects_wrong_models_crossing_words_and_weighted_confidence(self):
        data,rows,evidence=self.audio_evidence();evidence['x']['models'].pop('medium.en')
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)
        data,rows,evidence=self.audio_evidence()
        evidence['x']['models']['small.en']['segments'][0]['words'][0]['start']=.5
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)
        data,rows,evidence=self.audio_evidence();data['cues'][0]['source_audio_reading']="Can't I go"
        for m in evidence['x']['models'].values():
            m['segments'][0]['words']=[{'word':w,'start':1+i*.2,'end':1.2+i*.2,'probability':p}
                for i,(w,p) in enumerate([("Can't",.9),('I',.4),('go',.4)])]
        with self.assertRaises(ValueError):validate_source_readings(data,rows,evidence)

    def test_source_reading_can_exclude_neighbor_padding(self):
        data,rows,evidence=self.audio_evidence()
        for m in evidence['x']['models'].values():
            m['segments'][0]['words'].insert(0,{'word':'Hello','start':.7,'end':.85,'probability':.9})
        self.assertIn('x',validate_source_readings(data,rows,evidence))


if __name__=='__main__':unittest.main()
