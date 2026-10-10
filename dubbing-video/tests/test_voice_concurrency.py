"""Exercise the real OS lock with independent processes; paid API stays mocked."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dub_episode import ensure_voices
from translate import read_json, save_json


class VoiceConcurrencyTests(unittest.TestCase):
    def plan(self, root, episode=1):
        return {'project_id':59,'episode':episode,'voice_bank':str(root/'voice-bank.json'),
                'voices':{'Laura':{'segments_seconds':[[0,12]]}}}

    def test_two_processes_clone_same_role_once(self):
        script = '''
import sys,time
from pathlib import Path
import dub_episode as dub
root=Path(sys.argv[1]);episode=int(sys.argv[2]);folder=root/f'episode-{episode:02d}'
folder.mkdir(exist_ok=True)
def reference(source,segments,destination,ffmpeg):
    destination.write_bytes(b'fixture');return 12
dub.make_reference=reference
class Client:
    def upload(self,path):return 'https://example.invalid/reference.wav'
    def call(self,name,args):
        with (root/'paid-calls.txt').open('a') as f:f.write(name+'\\n')
        time.sleep(.3)
        return {'voiceId':args['request']['voiceId']}
plan={'project_id':59,'episode':episode,'voice_bank':str(root/'voice-bank.json'),
      'voices':{'Laura':{'segments_seconds':[[0,12]]}}}
dub.ensure_voices(plan,{'source_audio':Path('unused')},folder,Client(),None)
'''
        with tempfile.TemporaryDirectory() as tmp:
            children=[subprocess.Popen([sys.executable,'-c',script,tmp,str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                      for i in (1,2)]
            for child in children:
                stdout,stderr=child.communicate(timeout=20)
                self.assertEqual(child.returncode,0,stderr.decode(errors='replace'))
            root=Path(tmp)
            self.assertEqual((root/'paid-calls.txt').read_text().splitlines(),['uploadMiniMaxVoice'])
            self.assertEqual(len(read_json(root/'voice-bank.json')['voices']),1)
            self.assertEqual(len(list((root/'voice-clone-receipts').glob('*.private.json'))),1)

    def test_later_episode_recovers_legacy_clone_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt=root/'episode-01/dub-v1/clone-Laura.private.json'
            save_json(receipt,{'voiceId':'existing-fixture'})
            client=Mock()
            bank=ensure_voices(self.plan(root,2),{},root/'episode-02',client,None)
            self.assertEqual(bank['voices']['Laura']['voice_id'],'existing-fixture')
            client.call.assert_not_called();client.upload.assert_not_called()

    def test_ambiguous_legacy_clone_blocks_later_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            save_json(root/'episode-01/dub-v1/clone-Laura.private.submission-pending.json',{'tool':'uploadMiniMaxVoice'})
            client=Mock()
            with self.assertRaisesRegex(RuntimeError,'Ambiguous earlier clone'):
                ensure_voices(self.plan(root,2),{},root/'episode-02',client,None)
            client.call.assert_not_called();client.upload.assert_not_called()

    def test_process_exit_releases_lock(self):
        from process_lock import process_lock
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'guard.lock'
            with process_lock(path):
                with self.assertRaisesRegex(RuntimeError,'Another worker'):
                    with process_lock(path,timeout=0):pass
            with process_lock(path,timeout=0):pass

    def test_clone_timeout_blocks_retry_in_different_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'episode-01';folder.mkdir()
            client=Mock();client.upload.return_value='https://example.invalid/ref.wav'
            client.call.side_effect=TimeoutError('fixture: accepted then disconnected')
            with patch('dub_episode.make_reference',return_value=12):
                with self.assertRaises(TimeoutError):
                    ensure_voices(self.plan(root),{'source_audio':Path('unused')},folder,client,None)
            with self.assertRaisesRegex(RuntimeError,'Ambiguous earlier clone'):
                ensure_voices(self.plan(root,2),{},root/'episode-02',client,None)
            self.assertEqual(client.call.call_count,1)
            self.assertEqual(client.upload.call_count,1)
