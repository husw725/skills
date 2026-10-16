import copy
import json
from pathlib import Path
import tempfile
import unittest
from rerun_carmilla_season import request, validate_editorial, validate_reviewed_plan, storyboard_reference
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


if __name__=='__main__':unittest.main()
