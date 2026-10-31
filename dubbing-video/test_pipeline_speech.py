import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch
from translate import save_json
from dub_episode import digest
from generate_monte_episode01 import request_key, has_project
from pipeline_voice import voice_result, clone
from pipeline_speech import checked_units


class PaidIdentityTests(unittest.TestCase):
    def test_old_minimax_numeric_aliases_unchanged(self):
        a=dict(model='speech-2.8-hd',projectId=100,text='synthetic',voiceId='saved',speed=1,vol=1,pitch=0)
        b=dict(a,speed=1.0,vol=1.0,pitch=-0.0)
        self.assertEqual(request_key(a),request_key(b))
        for value in ('1',True,None):
            with self.assertRaises(ValueError):request_key(dict(a,speed=value))

    def test_cartesia_null_fields_remain_null(self):
        a=dict(model='sonic-3.6',projectId=96,text='synthetic',voiceId='cartesia:saved',speed=1,vol=None,pitch=None)
        self.assertNotEqual(request_key(a),request_key(dict(a,vol=1,pitch=0)))
        self.assertEqual(request_key(a),request_key(dict(a,speed=1.0)))

    def test_project_scope_is_explicit(self):
        self.assertTrue(has_project({'nested':[{'projectId':96}]},96))
        self.assertFalse(has_project({'nested':[{'projectId':100}]},96))

    def test_multi_role_cue_parts_cover_frozen_text(self):
        source=[dict(id='cue1',start=1.0,end=4.0)]
        candidate=dict(cues=[dict(id='cue1',translation='— Olá.\n— Oi.')])
        def unit(key,start,end,role,words):
            return dict(id=key,cue_id='cue1',start=start,end=end,role=role,translation=words,evidence='explicit source/script casting candidate',delivery_mode='dialogue',emotion='calm')
        decision=dict(holds=[],units=[unit('a',1,2,'alice','Olá.'),unit('b',2,4,'bob','Oi.')])
        checked_units(source,candidate,decision)
        decision['units'][1]['translation']='Omiti o sentido.'
        with self.assertRaises(ValueError):checked_units(source,candidate,decision)

    def test_source_hold_cannot_be_silently_spoken(self):
        source=[dict(id='cue1',start=1.0,end=4.0)]
        candidate=dict(cues=[dict(id='cue1',translation='Olá.')])
        decision=dict(holds=[dict(cue_id='cue1',reason='unresolved source')],units=[dict(id='a',cue_id='cue1',start=1,end=4,role='alice',translation='Olá.',evidence='candidate',delivery_mode='dialogue',emotion='calm')])
        with self.assertRaises(ValueError):checked_units(source,candidate,decision)

    def test_empty_source_translation_must_have_explicit_hold(self):
        source=[dict(id='cue1',start=1.,end=2.),dict(id='cue2',start=2.,end=3.)]
        candidate=dict(cues=[dict(id='cue1',translation='Olá.'),dict(id='cue2',translation='')])
        unit=dict(id='a',cue_id='cue1',start=1.,end=2.,role='alice',translation='Olá.',evidence='candidate',delivery_mode='dialogue',emotion='calm')
        with self.assertRaisesRegex(ValueError,'explicit hold'):
            checked_units(source,candidate,dict(units=[unit],holds=[]))
        checked_units(source,candidate,dict(units=[unit],holds=[dict(cue_id='cue2',reason='ASR fragment')]))

    def test_reference_tamper_after_prepare_prevents_clone_client(self):
        with tempfile.TemporaryDirectory() as directory:
            previous=os.getcwd()
            try:
                os.chdir(directory)
                root=Path('output/review-project-96/pipeline-voices-20261031/alice');root.mkdir(parents=True)
                wav=root/'reference.wav';wav.write_bytes(b'approved waveform')
                plan=dict(project_id=96,role='alice',platform='minimax',inputs_sha256={})
                reference=dict(plan_sha256='synthetic-plan',sha256=digest(wav))
                save_json(root/'plan-binding.private.json',dict(plan=plan,plan_sha256='synthetic-plan'))
                save_json(root/'reference-receipt.private.json',reference)
                wav.write_bytes(b'different waveform')
                with patch('mflix_client.Mflix') as client:
                    with self.assertRaisesRegex(ValueError,'Actual reference'):
                        clone(root,plan,reference,Path('unused-approval'),Path('unused-config'))
                    client.assert_not_called()
            finally:os.chdir(previous)

    def test_clone_identity_and_namespace(self):
        self.assertEqual(voice_result({'voiceId':'cartesia:synthetic','projectId':100},100,'priest','cartesia'),'cartesia:synthetic')
        for result in ({'voiceId':'saved','taskId':12},{'voiceId':'saved','projectId':96}):
            with self.assertRaises(ValueError):voice_result(result,100,'priest','minimax')
        with self.assertRaises(ValueError):voice_result({'voiceId':'saved'},100,'priest','cartesia')


if __name__=='__main__':unittest.main()
