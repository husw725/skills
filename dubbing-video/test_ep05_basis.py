import copy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import carmilla_ep05_basis as basis
from test_ep27_basis import words


class NameBasisTests(TestCase):
    def fixture(self):
        rows=[{'id':'e05-7','text':'Connor come in my bedroom','start':16.3,'end':18.733},
              {'id':'e05-26','text':'leave us your privacy sir','start':86.4,'end':88.933},
              {'id':'e05-35','text':'your eyes is do you have fever','start':111.1,'end':113.7},
              {'id':'e05-36','text':"no I'll just take a rest",'start':114.0,'end':116.4}]
        evidence={k:{'kept':True} for k in ['e05-7','e05-10','e05-20','e05-26','e05-35']}
        evidence['e05-35']={'models':{m:{'segments':[{'words':words('Your eyes do you have a fever',111.42)},{'words':words("No I'll just take a rest",113.51)}]} for m in ['small.en','medium.en']}}
        board={'entries':[{'storyboard':'Carmilla, come to my bedroom!'}]}
        root=Path('output/tools/source-asr-models/large-v3');files={str(root/f):'sha' for f in ['model.bin','config.json','tokenizer.json','preprocessor_config.json']}
        files[str(root/'model.bin')]='69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1'
        record={'input':{'cue':rows[0],'source_audio_sha256':'sha','source_review_sha256':'review',
            'clip_sha256':'sha','model_revision':'edaa852ec7e145841d8ffdb056a99866b5f0a478','official_metadata_sha256':'sha','model_files':files,
            'decoding':{'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':False,'word_timestamps':True,'vad_filter':False}},
            'segments':[{'words':words('Carmilla come to my bedroom',16.1)}],'human_listened':False,'source_speaker_verified':False}
        mapping={str(root/'official-source.json'):{'repo':'Systran/faster-whisper-large-v3','revision':record['input']['model_revision']}}
        for label,pad in [('context',2),('tight',.25)]:
            r=copy.deepcopy(record);r['input'].update(clip_start=16.3-pad,clip_end=18.733+pad,method='unprompted-local-large-v3-'+label)
            mapping[f'output/carmilla-source-large-20261019/episode-05/e05-7/{label}/large-v3.json']=r
        mapping['output/carmilla-source-verification-20261017/episode-05/e05-7/medium.en.json']={'input':{'source_review_sha256':'review'},'segments':[{'words':words('Camilla come to my bedroom',16.2)}]}
        return rows,evidence,board,{Path(k).as_posix():v for k,v in mapping.items()}

    def run_basis(self,rows,evidence,board,mapping):
        def sha(p):return '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1' if Path(p).name=='model.bin' else 'sha'
        with patch.object(basis,'read_json',side_effect=lambda p:mapping[Path(p).as_posix()]),patch.object(basis,'digest',side_effect=sha):
            return basis.reconstruct(rows,evidence,board,Path('source.wav'),'review')

    def test_editorial_name_and_privacy_preserve_conflicting_source(self):
        args=self.fixture();r,audio,inputs=self.run_basis(*args)
        self.assertEqual(set(r),{'e05-7','e05-26','e05-35'});self.assertEqual(set(audio),{'e05-10','e05-20'})
        self.assertEqual(r['e05-7']['original_subtitle_text'],'Connor come in my bedroom')
        self.assertEqual(r['e05-7']['source_basis'],'editorial_name_normalization');self.assertFalse(r['e05-7']['human_listened'])

    def test_old_source_or_storyboard_cannot_be_reused(self):
        for mode in ['time','text','board']:
            rows,ev,board,mapping=self.fixture()
            if mode=='time':rows[0]['end']+=1
            elif mode=='text':rows[1]['text']='leave us sir'
            else:board['entries'][0]['storyboard']='Connor come in my bedroom'
            with self.assertRaises(ValueError):self.run_basis(rows,ev,board,mapping)

    def test_changed_large_source_or_missing_phrase_is_blocked(self):
        for mode in ['source','review','phrase','model']:
            rows,ev,board,mapping=self.fixture();r=mapping['output/carmilla-source-large-20261019/episode-05/e05-7/tight/large-v3.json']
            if mode=='source':r['input']['source_audio_sha256']='wrong'
            elif mode=='review':r['input']['source_review_sha256']='wrong'
            elif mode=='phrase':r['segments'][0]['words'][0]['word']='Connor'
            else:r['input']['model_files']['extra']='sha'
            with self.assertRaises(ValueError):self.run_basis(rows,ev,board,mapping)

    def test_next_negation_requires_complete_bound_question_and_answer(self):
        rows,ev,board,mapping=self.fixture()
        ev['e05-35']['models']['medium.en']['segments'][1]['words'][0]['word']='Yes'
        with self.assertRaises(ValueError):self.run_basis(rows,ev,board,mapping)
        rows,ev,board,mapping=self.fixture();rows[-1]['text']="I'll just take a rest"
        with self.assertRaises(ValueError):self.run_basis(rows,ev,board,mapping)


class DiaryProductionTests(TestCase):
    def fixture(self):
        texts=["my daughter's blood is special",'It can purify darkness.','I sensed it the moment she was born']
        ids=['e05-23','e05-16','e05-17'];windows=[(62.566,64.066),(64.066,66.033),(66.066,68.333)]
        rows=[{'id':c,'text':t,'start':s,'end':e} for c,t,(s,e) in zip(ids,texts,windows)]
        old={c:{'id':f'e05-utterance-{i:03}','production_voice':'Mother'} for c,i in zip(ids,[16,17,18])}
        annotations={c:{'speaker':'unknown','speaker_audio_verified':False} for c in ids}
        board={'entries':[{'storyboard':' '.join(texts)}]}
        return rows,old,annotations,board

    def test_new_reading_retains_unidentified_original_actor(self):
        args=self.fixture();result=basis.diary_production_group(*args)
        self.assertEqual(result['source_reader'],'unknown');self.assertFalse(result['source_same_reader_confirmed'])
        self.assertEqual(result['production_voice'],'Mother');self.assertEqual(result['production_grouping_policy'],'single_written_diary_quote')
        self.assertTrue(all(a['speaker']=='unknown' for a in args[2].values()))

    def test_unknown_guard_still_blocks_unreviewed_group(self):
        from rerun_carmilla_season import validate_editorial
        rows,old,annotations,board=self.fixture();group=basis.diary_production_group(rows,old,annotations,board)
        data={'cues':[{'id':r['id'],'translation':'Texto.','script_evidence':'written quote','emotion':'calm','issues':[]} for r in rows],
              'groups':[[r['id'] for r in rows]]}
        with self.assertRaises(ValueError):validate_editorial(data,rows,old,annotations,{})
        validate_editorial(data,rows,old,annotations,{},unknown_production_groups=[group['cue_ids']])
        with self.assertRaises(ValueError):validate_editorial(data,rows,old,annotations,{},unknown_production_groups=[['unrelated']])

    def test_changed_quote_source_identity_or_casting_cannot_authorize(self):
        for mode in ['source','board','identity','casting','unit']:
            rows,old,annotations,board=self.fixture()
            if mode=='source':rows[0]['text']='Someone else blood is special'
            elif mode=='board':board['entries'][0]['storyboard']='different quote'
            elif mode=='identity':annotations['e05-23']['speaker']='Mother'
            elif mode=='casting':old['e05-23']['production_voice']='Laura'
            else:old['e05-23']['id']='different unit'
            with self.assertRaises(ValueError):basis.diary_production_group(rows,old,annotations,board)


class SpeechRepairTests(TestCase):
    def fixture(self):
        from resume_carmilla_reconciled import SPEECH_TRANSLATIONS
        prior={'cues':[{'id':c,'translation':'prior','emotion':'calm'} for c in [*SPEECH_TRANSLATIONS,'e05-7']],
               'groups':[['e05-23','e05-16','e05-17'],['e05-18','e05-19'],['e05-7']]}
        reviewed=copy.deepcopy(prior)
        for c in reviewed['cues']:c['translation']=SPEECH_TRANSLATIONS.get(c['id'],c['translation'])
        return prior,reviewed

    def test_only_exact_approved_five_texts_may_change(self):
        from resume_carmilla_reconciled import validate_retained_editorial,SPEECH_TRANSLATIONS
        prior,reviewed=self.fixture()
        validate_retained_editorial(reviewed,prior,SPEECH_TRANSLATIONS)
        for mode in ['text','locked','emotion','groups','missing','duplicate']:
            changed=copy.deepcopy(reviewed)
            if mode=='text':changed['cues'][0]['translation']='Purifica trevas.'
            elif mode=='locked':changed['cues'][-1]['translation']='Come here.'
            elif mode=='emotion':changed['cues'][0]['emotion']='angry'
            elif mode=='groups':changed['groups'][0].pop()
            elif mode=='missing':changed['cues'].pop()
            else:changed['cues'].append(copy.deepcopy(changed['cues'][0]))
            with self.assertRaises(ValueError):validate_retained_editorial(changed,prior,SPEECH_TRANSLATIONS)


    def test_v2_retains_successful_mother_text_and_other_paid_groups(self):
        from resume_carmilla_reconciled import validate_retained_editorial,SPEECH2_TRANSLATIONS
        _,prior=self.fixture();new=copy.deepcopy(prior)
        for c in new['cues']:c['translation']=SPEECH2_TRANSLATIONS.get(c['id'],c['translation'])
        validate_retained_editorial(new,prior,SPEECH2_TRANSLATIONS)
        new['cues'][0]['translation']='different mother text'
        with self.assertRaises(ValueError):validate_retained_editorial(new,prior,SPEECH2_TRANSLATIONS)


class VOAlignmentTests(TestCase):
    def fixture(self):
        return {'cue_ids':['e05-18','e05-19'],'production_voice':'Laura','start':68.866,'end':74.4}

    def test_only_this_internal_voiceover_can_enter_bounded_gap(self):
        from carmilla_ep05_alignment import validate_group,vo_window
        u=self.fixture();start,target,factor=vo_window(6.93,u,68.475)
        self.assertEqual(start,68.575);self.assertAlmostEqual(start+target,74.4)
        self.assertLessEqual(factor,1.2);self.assertAlmostEqual(start-68.475,.1)
        for field,value in [('cue_ids',['e05-18']),('production_voice','Carmilla'),('start',68.8),('end',75)]:
            with self.assertRaises(ValueError):validate_group(5,{**u,field:value})
        with self.assertRaises(ValueError):validate_group(8,u)
        with self.assertRaises(ValueError):vo_window(6.93,u,68.49)

    def test_cache_only_path_rejects_missing_changed_or_wrong_request(self):
        import tempfile
        from carmilla_ep05_alignment import completed_audio
        from translate import save_json,fingerprint
        from dub_episode import digest
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);req={'text':'approved','voiceId':'existing','speed':1.0}
            with self.assertRaises(FileNotFoundError):completed_audio(folder,req)
            audio=folder/'original.wav';audio.write_bytes(b'paid-audio')
            receipt={'task_id':42,'sha256':digest(audio)}
            save_json(folder/'request-fingerprint.json',{'fingerprint':fingerprint(req)})
            save_json(folder/'audio-receipt.json',receipt)
            self.assertEqual(completed_audio(folder,req)[0],audio)
            with self.assertRaises(ValueError):completed_audio(folder,{**req,'text':'changed'})
            audio.write_bytes(b'changed')
            with self.assertRaises(ValueError):completed_audio(folder,req)


    def test_full_basis_cannot_be_replaced_by_a_fingerprint_marker(self):
        import tempfile
        from carmilla_ep05_alignment import verify_basis
        from translate import save_json
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            save_json(folder/'audio-boundary-basis.private.json',{'plan_sha256':'approved'})
            save_json(folder/'audio-boundary-basis.json',{'fingerprint':'different'})
            with self.assertRaises(ValueError):verify_basis(folder,{})
