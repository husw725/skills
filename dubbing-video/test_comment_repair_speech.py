import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from dub_episode import digest
from generate_monte_episode01 import request_key
from generate_comment_repairs import validate,FIELDS,check_bridge,ADAPTER

class CommentSpeechTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.p=Path(self.t.name)
  self.req=dict(projectId=100,model='speech-2.8-hd',text='synthetic Portuguese text',voiceId='minimax:synthetic-a',languageBoost='Portuguese',format='wav',speed=1.0,vol=1.0,pitch=0,emotion='calm',duration=None,language=None,outputFormat=None,prompt=None,referenceVideoList=[])
  self.old=dict(project_id=100,episode=1,groups=[dict(id='old-a',role='a',request=copy.deepcopy(self.req))]);self.write('base.json',self.old)
  self.write('issues.json',dict(issues=[dict(comment_id=1,episode=1)]))
  self.g=dict(id='repair-a',source_group_id='old-a',role='a',comment_ids=[1],text=self.req['text'],request=copy.deepcopy(self.req),cache_key=request_key(self.req))
  self.plan=dict(project_id=100,episode=1,purpose='review_repair',new_clone_count=0,max_new_tts=1,baseline_plan=self.bind('base.json'),issue_matrix=self.bind('issues.json'),groups=[self.g],inputs_sha256={})
  self.save()
 def write(self,n,d):(self.p/n).write_text(json.dumps(d),encoding='utf-8')
 def bind(self,n):return dict(path=str(self.p/n),sha256=digest(self.p/n))
 def save(self):self.write('speech-plan.private.json',self.plan)
 def check(self):return validate(self.p/'speech-plan.private.json',run_routing=False)
 def test_same_actor_repair_preserves_exact_paid_identity(self):self.assertEqual(self.check()['groups'][0]['cache_key'],request_key(self.req))
 def test_wrong_role_or_unbound_voice_is_rejected(self):
  self.g['role']='b';self.save()
  with self.assertRaisesRegex(ValueError,'speaker'):self.check()
  self.g['role']='a';self.g['request']['voiceId']='minimax:other';self.g['cache_key']=request_key(self.g['request']);self.save()
  with self.assertRaises((KeyError,ValueError)):self.check()
 def test_changed_comment_or_parameter_hash_is_not_silently_reused(self):
  self.g['comment_ids']=[2];self.save()
  with self.assertRaisesRegex(ValueError,'comment'):self.check()
  self.g['comment_ids']=[1];self.g['request']['speed']=.96;self.save()
  with self.assertRaisesRegex(ValueError,'identity'):self.check()
 def test_audition_requires_actual_catalog_and_is_finite(self):
  self.plan['purpose']='voice_audition';self.g['request']['voiceId']='minimax:other';self.g['cache_key']=request_key(self.g['request']);self.save()
  with self.assertRaises((KeyError,ValueError)):self.check()
  self.write('catalog.json',dict(data=[dict(voiceId='minimax:other')]));self.plan['voice_catalog']=self.bind('catalog.json');self.save();self.check()
  self.plan['groups']=[dict(self.g,id=str(i),request=dict(self.g['request'],text=str(i)),text=str(i),cache_key=request_key(dict(self.g['request'],text=str(i)))) for i in range(3)];self.plan['max_new_tts']=3;self.save()
  with self.assertRaisesRegex(ValueError,'two-voice'):self.check()
 def test_bridge_rejects_self_consistent_wrong_speaker_or_endpoint(self):
  original=dict(cue_ids=['e01-1']);chunk=dict(envelope=dict(ADAPTER,payload=self.req),speaker='a',turn=dict(speaker='a',source_refs=[dict(cue_id='1')]))
  check_bridge(self.g,chunk,original)
  for part,key,value in [(chunk,'speaker','b'),(chunk['turn'],'speaker','b'),(chunk['envelope'],'endpoint','different')]:
   prior=part[key];part[key]=value
   with self.assertRaises(ValueError):check_bridge(self.g,chunk,original)
   part[key]=prior
  chunk['turn']['source_refs'][0]['cue_id']='2'
  with self.assertRaisesRegex(ValueError,'source cues'):check_bridge(self.g,chunk,original)
 def test_actual_routing_is_required_by_default(self):
  with patch('generate_comment_repairs.routing',side_effect=ValueError('routing failed')):
   with self.assertRaisesRegex(ValueError,'routing failed'):validate(self.p/'speech-plan.private.json')

if __name__=='__main__':unittest.main()
