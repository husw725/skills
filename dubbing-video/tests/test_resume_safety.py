import argparse
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import build_episode_plan as build
import dub_episode as dub
from translate import fingerprint,read_json,save_json


class ImmutablePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.previous=Path.cwd();os.chdir(self.tmp.name)
        self.folder=Path('output/drama-01/episode-04');source=Path('input/drama-01/episode-04')
        source.mkdir(parents=True);(self.folder/'media').mkdir(parents=True)
        for name in ('fixture.mp4','fixture_bgm.wav','fixture_sfx.wav'):(source/name).write_bytes(b'fixture')
        (self.folder/'media/source-audio.wav').write_bytes(b'fixture')
        save_json(self.folder/'media/media-manifest.json',{'warnings':[]})
        save_json(self.folder/'translation/speech-units.draft.json',{'units':[{
            'id':'u1','speaker':'Father','translation':'Oi.','start':0.,'end':12.}]})
        save_json(Path('output/drama-01/voice-bank.json'),{'voices':{}})

    def tearDown(self):
        os.chdir(self.previous);self.tmp.cleanup()

    def build(self):
        with patch('sys.argv',['build_episode_plan.py','--episode','4','--ffmpeg','fixture.exe']),patch.object(build.subprocess,'run'):
            build.main()
        return read_json(self.folder/'dub-plan-v1.json')

    def test_successful_clone_does_not_change_plan_on_restart(self):
        before=self.build();original=(self.folder/'dub-plan-v1.json').read_bytes()
        save_json(Path('output/drama-01/voice-bank.json'),{'voices':{'Father':{'voice_id':'fixture-existing'}}})
        after=self.build()
        self.assertEqual(after,before)
        self.assertEqual((self.folder/'dub-plan-v1.json').read_bytes(),original)
        assets={k:Path(v) for k,v in before['assets'].items()}
        save_json(self.folder/'dub-v1/input-fingerprint.json',{'fingerprint':fingerprint({
            'plan':before,'source_sha256':{k:dub.digest(p) for k,p in assets.items()}})})
        with patch.object(dub,'probe',return_value={'format':{'duration':'13'}}),patch.object(dub,'Mflix',side_effect=RuntimeError('Reached client')):
            with self.assertRaisesRegex(RuntimeError,'Reached client'):
                dub.render_episode(argparse.Namespace(ffmpeg=Path('fixture.exe'),mcp_config=Path('unused')),after)

    def test_changed_translation_preserves_original_plan_and_stops(self):
        self.build();path=self.folder/'dub-plan-v1.json';before=path.read_bytes()
        data=read_json(self.folder/'translation/speech-units.draft.json');data['units'][0]['translation']='Mudou.'
        save_json(self.folder/'translation/speech-units.draft.json',data)
        with self.assertRaisesRegex(ValueError,'existing plan preserved'):self.build()
        self.assertEqual(path.read_bytes(),before)


class SynthesisBindingTests(unittest.TestCase):
    def unit(self):
        return {'id':'u1','cue_ids':['c1'],'production_voice':'Laura','translation':'Oi.',
                'start':0.,'end':2.,'emotion':'calm','speed':1.05}

    def cache(self,root,unit):
        folder=root/unit['id'];folder.mkdir();audio=folder/'fitted.wav';audio.write_bytes(b'fixture')
        save_json(folder/'result.json',{'id':unit['id'],'cue_ids':unit['cue_ids'],'voice':'Laura','voice_id':'old',
                  'translation':unit['translation'],'start':unit['start'],'end':unit['end'],'requested_emotion':unit['emotion'],
                  'fitted_path':str(audio),'fitted_sha256':dub.digest(audio)})
        save_json(folder/'attempt-0.json',{'request_fingerprint':fingerprint(dub.tts_request(unit,'old',59,1.05,'calm'))})
        return folder

    def test_changed_voice_refuses_old_audio_without_regenerating(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);unit=self.unit();self.cache(root,unit);client=Mock()
            with self.assertRaisesRegex(ValueError,'Cached synthesis voice'):
                dub.synthesize(client,unit,'new',root,59,None)
            client.call.assert_not_called()

    def test_valid_legacy_cache_reused_without_paid_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);unit=self.unit();folder=self.cache(root,unit);client=Mock()
            saved=dub.synthesize(client,unit,'old',root,59,None)
            self.assertEqual(saved['voice_id'],'old');client.call.assert_not_called()
            self.assertTrue((folder/'synthesis-input.json').exists())

    def test_changed_speed_refuses_legacy_cache_without_paid_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);unit=self.unit();self.cache(root,unit);unit['speed']=1.2;client=Mock()
            with self.assertRaisesRegex(ValueError,'Legacy synthesis request differs'):
                dub.synthesize(client,unit,'old',root,59,None)
            client.call.assert_not_called()

    def test_partial_legacy_task_is_bound_before_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);unit=self.unit()
            save_json(folder/'attempt-0.json',{'request_fingerprint':fingerprint(dub.tts_request(unit,'old',59,1.05,'calm'))})
            dub.validate_synthesis_cache(folder,unit,'old',59)
            with self.assertRaisesRegex(ValueError,'Synthesis voice or inputs changed'):
                dub.validate_synthesis_cache(folder,unit,'new',59)
