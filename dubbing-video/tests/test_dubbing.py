import unittest
from pathlib import Path
import tempfile

from dub_episode import safe_submit, validate_units
from translate import save_json


class DubbingTests(unittest.TestCase):
    def unit(self,**kwargs):
        return {'id':'u1','start':0.,'end':1.,'translation':'Oi.','production_voice':'Laura','emotion':'calm',**kwargs}

    def test_unknown_voice_or_outside_timeline_never_submits(self):
        for unit in (self.unit(production_voice='unknown'),self.unit(end=2.),self.unit(start=-1.),self.unit(emotion='invented')):
            with self.assertRaises(ValueError):validate_units([unit],{'Laura':{}},1.)

    def test_ambiguous_submissions_are_not_automatically_charged_twice(self):
        class Client:
            def call(self,*args):raise TimeoutError('Simulated connection loss after submit')
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'result.json'
            with self.assertRaises(TimeoutError):safe_submit(Client(),'generateAudio',{'request':{}},path)
            with self.assertRaisesRegex(RuntimeError,'Ambiguous'):
                safe_submit(Client(),'generateAudio',{'request':{}},path)

    def test_saved_submission_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'result.json';save_json(path,{'taskId':42})
            self.assertEqual(safe_submit(None,'generateAudio',{},path),{'taskId':42})


if __name__=='__main__':unittest.main()

class MCPTransportTests(unittest.TestCase):
    def config(self,root):
        p=Path(root)/'private.json';save_json(p,{'url':'https://example.invalid/mcp','headers':{'Authorization':'Bearer fixture-only'}});return p

    def response(self,result):
        from unittest.mock import Mock
        import json
        return Mock(status_code=200,headers={},text=json.dumps({'jsonrpc':'2.0','id':1,'result':result}))

    def test_generation_connection_failure_is_not_retried(self):
        import requests
        from unittest.mock import patch
        from mflix_client import Mflix
        with tempfile.TemporaryDirectory() as root,patch('requests.Session') as session:
            session.return_value.post.side_effect=[self.response({'serverInfo':{}}),requests.ConnectionError('fixture')]
            client=Mflix(self.config(root))
            with self.assertRaisesRegex(RuntimeError,'submission status'):
                client.rpc('tools/call',{'name':'generateAudio','arguments':{}})
            self.assertEqual(session.return_value.post.call_count,2)

    def test_read_only_connection_failure_can_retry(self):
        import requests
        from unittest.mock import patch
        from mflix_client import Mflix
        with tempfile.TemporaryDirectory() as root,patch('requests.Session') as session,patch('mflix_client.time.sleep'):
            session.return_value.post.side_effect=[self.response({'serverInfo':{}}),requests.ConnectionError('fixture'),self.response({'content':[]})]
            client=Mflix(self.config(root));client.rpc('tools/call',{'name':'getTaskById','arguments':{'taskId':42}})
            self.assertEqual(session.return_value.post.call_count,3)
