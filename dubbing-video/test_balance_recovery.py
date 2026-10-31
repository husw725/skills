import tempfile,os,unittest,wave
from pathlib import Path
from unittest.mock import patch
import generate_monte_episode01 as speech
from recover_balance_speech import validate_permit
from translate import save_json,fingerprint
from dub_episode import digest

class BalanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.previous=os.getcwd();os.chdir(self.tmp.name)
        self.req=dict(projectId=100,model='speech-2.8-hd',text='Teste.',voiceId='existing',speed=1,vol=1,pitch=0)
        self.key=speech.request_key(self.req);base=Path('output/review-project-100');self.cache=base/'paid-speech-cache';self.old=self.cache/self.key;self.new=base/'paid-speech-balance-recovery-01'/self.key
        for folder,task,status in ((self.old,99,3),(self.new,100,2)):
            folder.mkdir(parents=True);save_json(folder/'request.private.json',dict(key=self.key,request=self.req));save_json(folder/'submission.private.json',dict(taskId=task));save_json(folder/'task.private.json',dict(task_id=task,result=dict(taskId=task,taskStatus=status,taskMessage='insufficient balance' if status==3 else 'OK')))
        raw=self.new/'raw.wav'
        with wave.open(str(raw),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(32000);w.writeframes(b'\x00\x04'*3200)
        save_json(self.new/'raw-receipt.private.json',dict(key=self.key,task_id=100,request_fingerprint=fingerprint(self.req),status_sha256=digest(self.new/'task.private.json'),bytes=raw.stat().st_size,sha256=digest(raw),wave=speech.wave_evidence(raw)))
        plan=base/'plan.json';save_json(plan,dict(groups=[dict(cache_key=self.key,request=self.req)],inputs_sha256={}))
        audit=base/'audit.txt';audit.write_text('explicit terminal balance failure candidate recovery')
        self.permit=base/'permit.json';self.value=dict(project_id=100,key=self.key,original_task_id=99,max_new_submissions=1,approved_once=True,original_sha256={n:digest(self.old/n) for n in ('request.private.json','submission.private.json','task.private.json')},plan_path=str(plan),plan_sha256=digest(plan),audit_report_path=str(audit),audit_report_sha256=digest(audit));save_json(self.permit,self.value)
        save_json(self.old/'balance-recovery-link.private.json',dict(key=self.key,target=str(self.new),original_task_id=99,original_sha256=self.value['original_sha256'],permit_path=str(self.permit),permit_sha256=digest(self.permit),recovery_task_id=100,recovery_receipt_sha256=digest(self.new/'raw-receipt.private.json')))
        save_json(self.cache/'submission-attempts.private.json',dict(project_id=100,attempts={self.key:dict(task_id=99,request_fingerprint=fingerprint(self.req))}))
    def tearDown(self):os.chdir(self.previous);self.tmp.cleanup()
    def test_complete_recovery_reuses_audio_without_rewriting_original_ledger(self):
        validate_permit(self.value,self.old,self.key,self.req)
        with patch.object(speech,'CACHE',self.cache):a=speech.preflight_cache({self.key:self.req},100)
        self.assertEqual(a[self.key][1],100);self.assertEqual(speech._read_cache_origin(self.old,self.key,self.req)[1],99)
        self.assertFalse((self.old/'raw.wav').exists())
    def test_original_tamper_rejected(self):
        save_json(self.old/'submission.private.json',dict(taskId=98))
        with self.assertRaises(ValueError):speech.read_cache(self.old,self.key,self.req)
    def test_pending_or_failed_recovery_never_adopted(self):
        save_json(self.new/'task.private.json',dict(task_id=100,result=dict(taskId=100,taskStatus=1)))
        with self.assertRaises(ValueError):speech.read_cache(self.old,self.key,self.req)
    def test_cartesia_or_nonterminal_origin_cannot_be_retried(self):
        with self.assertRaises(ValueError):validate_permit(self.value,self.old,self.key,dict(self.req,model='sonic-3.6'))
        save_json(self.old/'task.private.json',dict(task_id=99,result=dict(taskStatus=1)))
        with self.assertRaises(ValueError):validate_permit(self.value,self.old,self.key,self.req)

if __name__=='__main__':unittest.main()
