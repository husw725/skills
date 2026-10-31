import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dub_episode import digest
from translate import save_json
import pipeline_casting_extension as extension


class CastingExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.getcwd(); os.chdir(self.temp.name)
        self.addCleanup(self.cleanup)
        self.root = Path('episode'); self.root.mkdir()
        self.parent_path = self.root/'parent.json'
        self.old_root = self.root/'pipeline-audio-20261031-v1'; self.old_root.mkdir()
        source = self.root/'source-input.private.json'
        save_json(source, {'timed_source': [{'id': 'e04-1', 'start': 0, 'end': 1},
                                            {'id': 'e04-2', 'start': 2, 'end': 3}]})
        self.old_unit = dict(id='old-unit', cue_id='e04-1', start=0, end=1,
                             role='hero', translation='Oi.', evidence='script',
                             delivery_mode='dialogue', emotion='calm')
        self.new_unit = dict(id='new-unit', cue_id='e04-2', start=2, end=3,
                             role='guard', translation='Pare.', evidence='script',
                             delivery_mode='dialogue', emotion='calm',
                             original_script_role='unknown', source_speaker_audio_verified=False)
        self.parent = dict(project_id=100, episode=4, units=[self.old_unit],
                           holds=[dict(cue_id='e04-2', reason='Source multi-role/unknown requires explicit production casting')],
                           baseline_result_sha256='same', source_input_sha256='same', media_receipt_path='media')
        save_json(self.parent_path, self.parent)
        self.old_group = dict(id='old-group', role='hero', start=0, end=1, cache_key='old-key',
                              request={'voiceId': 'old-voice'}, unit_ids=['old-unit'])
        self.old = dict(project_id=100, episode=4, groups=[self.old_group],
                        inputs_sha256={str(source): digest(source)},
                        production_cues=[dict(id='e04-1', translation='Oi.'), dict(id='e04-2', translation='Pare.')],
                        holds=self.parent['holds'])
        save_json(self.old_root/'speech-plan.private.json', self.old)
        raw = self.root/'raw.wav'; raw.write_bytes(b'unchanged paid audio')
        self.receipt = {'sha256': digest(raw)}
        result = dict(plan_sha256=digest(self.old_root/'speech-plan.private.json'),
                      groups=[dict(group_id='old-group', key='old-key', task_id=123,
                                   raw_path=str(raw), raw_sha256=digest(raw))])
        save_json(self.old_root/'generation-result.private.json', result)
        audit = self.root/'audit.md'; audit.write_text('Independent review')
        evidence = self.root/'evidence.json'
        save_json(evidence, {'unknown_27': [dict(cue_id='e04-2', episode=4,
                   production_role_candidate='guard', translation_unchanged='Pare.')]})
        self.decision = {**self.parent, 'production_revision': 2,
                         'units': [self.old_unit, self.new_unit], 'holds': [],
                         'audit_report_path': str(audit), 'audit_report_sha256': digest(audit),
                         'casting_extension': dict(parent_decision_path=str(self.parent_path),
                         parent_decision_sha256=digest(self.parent_path),
                         parent_plan_sha256=digest(self.old_root/'speech-plan.private.json'),
                         parent_generation_sha256=digest(self.old_root/'generation-result.private.json'),
                         cue_ids=['e04-2'], voice_manifest_path='voices.json',
                         cue_evidence_path=str(evidence), cue_evidence_sha256=digest(evidence))}
        self.path = self.root/'extension.json'

    def cleanup(self):
        os.chdir(self.previous); self.temp.cleanup()

    def build(self):
        save_json(self.path, self.decision)
        with patch.object(extension.pipeline, 'build', return_value=self.old), \
             patch.object(extension, 'reused_voices', return_value={'guard': {'voice_id': 'saved-voice', 'platform': 'minimax'}}), \
             patch.object(extension.speech, 'read_cache', return_value=({'voiceId': 'old-voice'}, 123, self.receipt)):
            return extension.build(self.path)

    def test_addition_preserves_original_paid_group_and_has_own_cap(self):
        plan = self.build()
        self.assertEqual(plan['groups'][0], self.old_group)
        self.assertEqual(plan['casting_extension']['new_request_limit'], 1)
        self.assertEqual(plan['groups'][1]['request']['projectId'], 100)

    def test_missing_paid_audio_never_falls_back_to_paid_resubmission(self):
        self.receipt = None
        with self.assertRaisesRegex(ValueError, 'Previously paid audio'):
            self.build()

    def test_original_unit_text_change_refused(self):
        self.decision['units'] = [dict(self.old_unit, translation='changed'), self.new_unit]
        with self.assertRaisesRegex(ValueError, 'Original paid units'):
            self.build()

    def test_source_timeline_hold_cannot_be_removed_as_casting(self):
        self.parent['holds'][0]['reason'] = 'Source timeline mismatch'
        save_json(self.parent_path, self.parent)
        self.decision['casting_extension']['parent_decision_sha256'] = digest(self.parent_path)
        save_json(self.old_root/'speech-plan.private.json', self.old)
        self.decision['casting_extension']['parent_plan_sha256'] = digest(self.old_root/'speech-plan.private.json')
        from translate import read_json
        result_path = self.old_root/'generation-result.private.json'
        result = read_json(result_path)
        result['plan_sha256'] = self.decision['casting_extension']['parent_plan_sha256']
        save_json(result_path, result)
        self.decision['casting_extension']['parent_generation_sha256'] = digest(result_path)
        with self.assertRaisesRegex(ValueError, 'Only casting holds'):
            self.build()

    def test_existing_group_spanning_added_cue_is_rejected_before_spend(self):
        self.old_group['end'] = 2.5
        save_json(self.old_root/'speech-plan.private.json', self.old)
        self.decision['casting_extension']['parent_plan_sha256'] = digest(self.old_root/'speech-plan.private.json')
        generated = self.old_root/'generation-result.private.json'
        from translate import read_json
        value = read_json(generated)
        value['plan_sha256'] = self.decision['casting_extension']['parent_plan_sha256']
        save_json(generated, value)
        self.decision['casting_extension']['parent_generation_sha256'] = digest(generated)
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.build()

    def test_old_group_request_or_order_cannot_change(self):
        changed = copy.deepcopy(self.old_group); changed['request']['voiceId'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'Paid groups changed'):
            extension.preserved_groups([self.old_group], [changed])

    def test_only_added_request_enters_paid_generator(self):
        plan = self.build()
        root = extension.pipeline.audio_root(self.path); root.mkdir()
        save_json(root/'speech-plan.private.json', plan)
        save_json(root/'candidate-plan-check.private.json', {'review': 'synthetic'})
        calls = []
        previous_root, previous_cache = extension.speech.ROOT, extension.speech.CACHE
        self.addCleanup(setattr, extension.speech, 'ROOT', previous_root)
        self.addCleanup(setattr, extension.speech, 'CACHE', previous_cache)
        extension.speech.CACHE = Path('cache')
        def fake_generate(delta, config, **kwargs):
            calls.append(delta)
            self.assertEqual(delta, kwargs['current_plan_builder']())
            self.assertEqual(delta['max_new_tts'], 1)
            self.assertNotIn('old-key', {g['cache_key'] for g in delta['groups']})
            save_json(extension.speech.ROOT/'generation-result.private.json', {'new_submission_attempts': 1})
        def cached(folder, key, request):
            return request, 123 if key == 'old-key' else 456, dict(sha256='verified', wave={'seconds': .5})
        with patch.object(extension, 'build', return_value=plan), \
             patch.object(extension.speech, 'generate', side_effect=fake_generate), \
             patch.object(extension.speech, 'read_cache', side_effect=cached), \
             patch.object(extension.speech, 'recovery_folder', side_effect=lambda folder, *_: folder):
            extension.generate(plan, self.path, Path('unused'))
        self.assertEqual(len(calls), 1)
        from translate import read_json
        combined = read_json(root/'generation-result.private.json')
        self.assertEqual([r['task_id'] for r in combined['groups']], [123, 456])


if __name__ == '__main__': unittest.main()
