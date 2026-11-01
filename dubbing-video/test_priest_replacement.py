import copy
import unittest
from replace_unresolved_priest import replacement_plan


class PriestReplacementTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(project_id=100, episode=2, holds=[], groups=[
            dict(id=f'p100-e02-g{i:03d}', role='wedding_priest' if i == 9 else 'other',
                 text=f'Synthetic sentence {i}', start=i, end=i+.8, cue_ids=[str(i)],
                 request=dict(model='sonic-3.6' if i == 9 else 'speech-2.8-hd'), cache_key=str(i))
            for i in range(1,21)], production_cues=[dict(id='synthetic')], subtitle_text='synthetic')
        self.req = dict(projectId=100, model='speech-2.8-hd', text='Synthetic sentence 9',
            voiceId='minimax:Portuguese_ReliableMan', languageBoost='Portuguese', format='wav',
            speed=1.0, vol=1.0, pitch=0, emotion='calm', duration=None, language=None,
            outputFormat=None, prompt=None, referenceVideoList=[])

    def test_only_one_request_changes_and_original_is_untouched(self):
        original=copy.deepcopy(self.old);new=replacement_plan(self.old,self.req)
        self.assertEqual(self.old,original)
        self.assertEqual([a['id'] for a,b in zip(new['groups'],self.old['groups']) if a!=b],['p100-e02-g009'])
        self.assertEqual(new['production_cues'],self.old['production_cues'])
        self.assertEqual(new['subtitle_text'],self.old['subtitle_text'])
        self.assertEqual({k:v for k,v in new['groups'][8].items() if k not in ('request','cache_key')},
                         {k:v for k,v in self.old['groups'][8].items() if k not in ('request','cache_key')})

    def test_changed_text_voice_locale_or_speed_rejected(self):
        for key,value in [('text','Different words'),('voiceId','Portuguese_ReliableMan'),
                          ('languageBoost','English'),('speed',1.1),('emotion','auto')]:
            r={**self.req,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):replacement_plan(self.old,r)

    def test_wrong_scope_or_already_changed_model_rejected(self):
        for field,value in [('episode',3),('project_id',96),('holds',[dict(cue_id='x')])]:
            old={**self.old,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):replacement_plan(old,self.req)
        self.old['groups'][8]['request']['model']='speech-2.8-hd'
        with self.assertRaises(ValueError):replacement_plan(self.old,self.req)


if __name__=='__main__':unittest.main()
