import tempfile
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

    def test_special_existing_first_episode_path(self):
        self.assertIn('20261030', str(queue.folder_for(100, 1)))
        self.assertIn('20261031', str(queue.folder_for(96, 1)))


if __name__ == '__main__':
    unittest.main()
