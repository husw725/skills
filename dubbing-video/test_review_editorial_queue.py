import tempfile
import os
import json
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import subprocess
import prepare_review_editorial_queue as queue


class QueueResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.calls = []
        self.ready = dict(status='text_candidate_ready', result_sha256='a', subtitle_sha256='b', cue_count=2)

    def runner(self, project, episode):
        self.calls.append((project, episode))
        return 0

    def validate(self, *args):
        return dict(self.ready)

    def step(self, prior=None, runner=None):
        with patch.object(queue, 'folder_for', return_value=self.folder):
            return queue.step(96, 1, prior, self.validate, runner or self.runner)

    def test_existing_output_is_read_only(self):
        (self.folder/'editorial-result.private.json').write_text('{}')
        self.assertEqual(self.step(), self.ready)
        self.assertFalse(self.calls)

    def test_unknown_previous_attempt_does_not_launch(self):
        result = self.step(dict(status='submission_reserved'))
        self.assertEqual(result['status'], 'needs_reconciliation')
        self.assertFalse(self.calls)

    def test_completed_output_reconciles_interrupted_state(self):
        (self.folder/'editorial-result.private.json').write_text('{}')
        self.assertEqual(self.step(dict(status='running')), self.ready)
        self.assertFalse(self.calls)

    def test_changed_completed_output_rejected(self):
        (self.folder/'editorial-result.private.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.step(dict(self.ready, subtitle_sha256='changed'))
        self.assertFalse(self.calls)

    def test_new_episode_runs_once(self):
        self.assertEqual(self.step(), self.ready)
        self.assertEqual(self.calls, [(96, 1)])

    def test_failure_is_retained(self):
        result = self.step(runner=lambda *args: 1)
        self.assertEqual(result['exit_code'], 1)
        self.assertFalse(result['automatic_retry'])

    def test_changed_hash_stays_pinned_after_error(self):
        (self.folder/'editorial-result.private.json').write_text('{}')
        prior = dict(self.ready, subtitle_sha256='changed', status='needs_reconciliation')
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.step(prior)
        self.assertFalse(self.calls)

    def test_current_basis_changes_are_rejected(self):
        original = dict(timed_source=[dict(text='No', start=1)], quality_policy_sha256='policy',
                        series_context_sha256='bible', physical_inputs_sha256={'screenplay':'source'})
        queue.check_basis(original, dict(original))
        for key in original:
            with self.assertRaises(ValueError):
                queue.check_basis(original, dict(original, **{key: 'modified'}))

    def test_uncertain_kill_is_fatal(self):
        process = Mock(pid=123)
        with patch.object(queue.subprocess, 'run', side_effect=subprocess.TimeoutExpired('taskkill', 25)):
            with self.assertRaises(RuntimeError):
                queue.terminate_child(process)
        process.wait.assert_not_called()

    def test_uncertain_exit_is_fatal(self):
        process = Mock(pid=123)
        process.wait.side_effect = subprocess.TimeoutExpired('child', 25)
        with patch.object(queue.subprocess, 'run', return_value=Mock(returncode=0)):
            with self.assertRaises(RuntimeError):
                queue.terminate_child(process)

    def test_notification_intent_deduplicates_unknown_delivery(self):
        config = self.folder/'config.json'
        config.write_text('{}')
        state = dict(project_id=96, scope=[1,2], ready=1, episodes={'2':dict(status='needs_reconciliation')})
        saves = []
        sender = Mock(side_effect=TimeoutError('network'))
        def persist():
            saves.append(dict(state.get('notification', {})))
        queue.notify_blocker(state, persist, config, sender)
        queue.notify_blocker(state, persist, config, sender)
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(saves[0]['status'], 'submitting')
        self.assertEqual(state['notification']['status'], 'delivery_failed_or_unknown')

    def test_special_existing_first_episode_path(self):
        self.assertIn('20261030', str(queue.folder_for(100, 1)))
        self.assertIn('20261031', str(queue.folder_for(96, 1)))


class EditorialFallbackTests(unittest.TestCase):
    def test_known_invalid_response_can_use_only_pinned_fallback(self):
        import prepare_review_episode_editorial as worker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root/'.codex/models_cache.json'
            cache.parent.mkdir()
            cache.write_text(json.dumps({'models':[{'slug':m,'visibility':'list'} for m in worker.context_worker.MODEL_ORDER]}))
            models = list(worker.context_worker.MODEL_ORDER[:2])
            stage = root/'stage'
            called = []
            def call(exe, model, prompt, folder):
                called.append(model)
                path = folder/(model+'.response.private.json')
                path.write_text(json.dumps({'valid':model == models[1]}))
                return dict(status='response_received',output=str(path),sha256=queue.digest(path))
            def validate(data, *args):
                if not data['valid']:
                    raise ValueError('Empty translation')
            with patch.dict(os.environ, USERPROFILE=str(root)), patch.object(worker.context_worker,'call_model',side_effect=call), patch.object(worker,'validate',side_effect=validate):
                result, receipt = worker.get_response('unused','synthetic prompt',stage,[],{})
            self.assertEqual(called, models)
            self.assertEqual(receipt['model'], models[1])
            self.assertFalse(json.loads((stage/(models[0]+'.response.private.json')).read_text())['valid'])
            self.assertEqual(json.loads((stage/(models[0]+'.validation.private.json')).read_text())['status'], 'rejected')

    def test_unknown_completion_never_uses_fallback(self):
        import prepare_review_episode_editorial as worker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root/'.codex/models_cache.json'
            cache.parent.mkdir()
            cache.write_text(json.dumps({'models':[{'slug':m,'visibility':'list'} for m in worker.context_worker.MODEL_ORDER]}))
            call = Mock(return_value={'status':'timeout'})
            with patch.dict(os.environ, USERPROFILE=str(root)), patch.object(worker.context_worker,'call_model',call):
                with self.assertRaisesRegex(ValueError,'do not resubmit'):
                    worker.get_response('unused','synthetic',root/'stage',[],{})
            self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
