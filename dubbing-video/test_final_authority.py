import copy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from carmilla_final_authority import SPECS,reconstruct
from rerun_carmilla_season import STORYBOARD_MAPPING_SHA256


class FinalAuthorityTests(TestCase):
    def fixture(self,n):
        rows=[{'id':c,'text':s[0],'start':s[1],'end':s[2]} for c,s in SPECS[n].items()]
        reference={'entries':[{'storyboard_episode':'EP-08' if n==8 else 'EP-30','storyboard':' '.join(s[3] for s in SPECS[n].values())}]}
        evidence={r['id']:{'cue':copy.deepcopy(r),'models':{'small.en':{'segments':[]},'medium.en':{'segments':[]}},'source_speaker_verified':False} for r in rows}
        authority={'kind':'user_final_storyboard_editorial_resolution','user_instruction':'按final来定',
            'approved_source_cues':['e08-6','e29-8'],'storyboard_sha256':STORYBOARD_MAPPING_SHA256,
            'audio_listened':False,'speaker_verified':False,'approved_translations':{c:s[-1] for c,s in SPECS[n].items()},
            'audit_report':{'path':'audit','sha256':'sha'},'evidence_packet':{'path':'packet','sha256':'sha'},
            'original_subtitle':{'path':str(Path('input/drama-01/subtitles/original/短剧/carmilla/06SRT字幕')/('carmilla_Ep08.srt' if n==8 else 'Carmilla_EP29.srt')),'sha256':'sha'}}
        return rows,reference,evidence,authority

    def run_case(self,n,args):
        with patch('dub_episode.digest',return_value='sha'):return reconstruct(n,*args)

    def test_explicit_user_meaning_preserves_original_and_unheard_evidence(self):
        for n in [8,29]:
            rows,ref,ev,auth=self.fixture(n);result=self.run_case(n,(rows,ref,ev,auth))
            for row in rows:
                r=result[row['id']];self.assertEqual(r['original_subtitle_text'],row['text'])
                self.assertFalse(r['human_listened']);self.assertFalse(r['source_speaker_verified'])
                self.assertEqual(r['complete_asr_records'],ev[row['id']]['models'])
            if n==29:self.assertEqual(result['e29-19']['source_basis'],'editorial_subtitle_confirmation')

    def test_wrong_authority_mapping_source_or_translation_cannot_resolve(self):
        for mode in ['user','scope','boardsha','mapped','quote','source','time','translation','human','identity','srt','packet']:
            rows,ref,ev,auth=self.fixture(29)
            if mode=='user':auth['user_instruction']='continue'
            elif mode=='scope':auth['approved_source_cues'].append('e29-9')
            elif mode=='boardsha':auth['storyboard_sha256']='old'
            elif mode=='mapped':ref['entries'][0]['storyboard_episode']='EP-29'
            elif mode=='quote':ref['entries'][0]['storyboard']='How many years'
            elif mode=='source':rows[0]['text']='How many?'
            elif mode=='time':rows[0]['end']+=1
            elif mode=='translation':auth['approved_translations']['e29-8']='Quantos anos?'
            elif mode=='human':auth['audio_listened']=True
            elif mode=='identity':ev['e29-8']['source_speaker_verified']=True
            elif mode=='srt':auth['original_subtitle']['path']='another.srt'
            else:auth['evidence_packet']['sha256']='old'
            with self.assertRaises(ValueError):self.run_case(29,(rows,ref,ev,auth))
