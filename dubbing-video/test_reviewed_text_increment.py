import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from translate import save_json
from dub_episode import digest
import generate_reviewed_text_increment as worker


class OneTextRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.previous=os.getcwd(); os.chdir(self.temp.name)
        self.addCleanup(self.cleanup)
        request=dict(text='Old words.',voiceId='saved',speed=1.,emotion='calm',projectId=100,model='speech-2.8-hd')
        g=dict(id='p100-e16-g011',role='banker',start=1,end=3,text='Old words.',cache_key='old-key',request=request)
        self.old=dict(project_id=100,episode=16,groups=[g],media={'video':'same','background':'same'},holds=[],
                      production_cues=[dict(id='e16-14',start=1,end=3,translation='Old words.')])
        self.new=copy.deepcopy(self.old)
        self.new['groups'][0].update(text='New words.',cache_key='new-key')
        self.new['groups'][0]['request']['text']='New words.'
        self.new['production_cues'][0]['translation']='New words.'
        save_json('review.json',{'freeze_proposal':dict(text='New words.',cue_translations={'e16-14':'New words.'},change_only_cue_ids=['e16-14'])})
        save_json('parent.json',{}); save_json('decision.json',{})
        self.permit=dict(project_id=100,episode=16,max_new_requests=1,new_clones=0,group_id='p100-e16-g011',
                         parent_decision_path='parent.json',decision_path='decision.json',text_review_path='review.json',
                         new_request_key='new-key',inputs_sha256={p:digest(p) for p in ['review.json','parent.json','decision.json']})

    def cleanup(self): os.chdir(self.previous);self.temp.cleanup()

    def check(self):
        save_json('permit.json',self.permit)
        with patch.object(worker,'checked_parent',return_value=(Path('old-audio'),self.old,{})), \
             patch.object(worker.pipeline,'build',side_effect=[self.old,self.new]):
            return worker.checked(Path('permit.json'))

    def test_only_one_reviewed_text_and_matching_subtitle_is_accepted(self):
        self.assertEqual(self.check()[2],self.new)

    def test_wrong_group_or_unbound_review_rejected(self):
        self.permit['group_id']='p100-e16-g012'
        with self.assertRaisesRegex(ValueError,'Only the reviewed'):self.check()
        self.permit['group_id']='p100-e16-g011';del self.permit['inputs_sha256']['review.json']
        with self.assertRaisesRegex(ValueError,'hash-bound'):self.check()

    def test_same_text_but_changed_voice_or_speed_is_rejected(self):
        for field,value in [('voiceId','different'),('speed',1.1),('emotion','angry')]:
            with self.subTest(field=field):
                original=self.new['groups'][0]['request'][field]
                self.new['groups'][0]['request'][field]=value
                with self.assertRaisesRegex(ValueError,'synthesis parameters'):self.check()
                self.new['groups'][0]['request'][field]=original

    def test_role_or_subtitle_time_change_is_rejected(self):
        self.new['groups'][0]['role']='another'
        with self.assertRaisesRegex(ValueError,'role, acting'):self.check()
        self.new['groups'][0]['role']='banker'
        self.new['production_cues'][0]['end']=4
        with self.assertRaisesRegex(ValueError,'cue identity or time'):self.check()

    def test_subtitle_must_match_reviewed_spoken_words(self):
        self.new['production_cues'][0]['translation']='Unreviewed words.'
        with self.assertRaisesRegex(ValueError,'Subtitle wording'):self.check()


if __name__=='__main__':unittest.main()
