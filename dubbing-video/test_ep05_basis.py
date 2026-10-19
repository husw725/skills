import copy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import carmilla_ep05_basis as basis
from test_ep27_basis import words


class NameBasisTests(TestCase):
    def fixture(self):
        rows=[{'id':'e05-7','text':'Connor come in my bedroom','start':16.3,'end':18.733},
              {'id':'e05-26','text':'leave us your privacy sir','start':86.4,'end':88.933}]
        evidence={k:{'kept':True} for k in ['e05-7','e05-10','e05-20','e05-26','e05-35']}
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
        self.assertEqual(set(r),{'e05-7','e05-26'});self.assertEqual(set(audio),{'e05-10','e05-20','e05-35'})
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
