import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_update as d


class PublishTests(unittest.TestCase):
    def test_unchanged_paths_continue_to_push_and_pages_despite_other_local_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/x.json').write_text('{}', encoding='utf-8')
            (root / 'report.html').write_text('report', encoding='utf-8')
            (root / 'other.txt').write_text('original', encoding='utf-8')
            def git(args):
                return subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                                       '-c', 'commit.gpgsign=false', *args], cwd=tmp, capture_output=True, text=True)
            for args in (['init', '-q'], ['add', '.'], ['commit', '-qm', 'fixture']):
                self.assertEqual(git(args).returncode, 0)
            (root / 'other.txt').write_text('keep this change', encoding='utf-8')
            (root / 'untracked.txt').write_text('keep this file', encoding='utf-8')
            commands = []
            def run(cmd, cwd=None):
                commands.append(cmd)
                if cmd[1] in ('push', 'pull'):
                    return subprocess.CompletedProcess(cmd, 0, '', '')
                return git(cmd[1:])
            with patch.object(d, 'run_git', side_effect=run), patch.object(d, 'sync_s3', return_value=True), \
                 patch.object(d, 'sync_pages_repo', return_value=True) as pages, patch.object(d, 'git_stuck', return_value=None), \
                 patch.object(d, 'notify_once') as notify, patch.object(d, 'alert_clear'), \
                 patch.object(d, 'alert_clear_all'), patch.object(d, 'log'):
                self.assertEqual(d.publish_report('2026-11-08', True, None), 0)
            self.assertTrue(pages.called)
            self.assertTrue(any(cmd[1] == 'push' for cmd in commands))
            self.assertFalse(any(cmd[1] == 'commit' for cmd in commands))
            notify.assert_not_called()
            self.assertEqual((root / 'other.txt').read_text(encoding='utf-8'), 'keep this change')
            self.assertIn(' M other.txt', git(['status', '--short']).stdout)

    def test_commit_and_diff_errors_remain_failures(self):
        cmd = ['git', 'commit', '--only', '-m', 'report', '--', 'index.html', 'data']
        changed = subprocess.CompletedProcess([], 1, '', '')
        failed = subprocess.CompletedProcess([], 128, '', 'permission denied')
        with patch.object(d, 'run_git', side_effect=[changed, failed]) as run:
            self.assertIs(d.run_publish_git(cmd), failed)
            self.assertEqual(run.call_count, 2)
        with patch.object(d, 'run_git', return_value=failed) as run:
            self.assertIs(d.run_publish_git(cmd), failed)
            self.assertEqual(run.call_count, 1)

    def test_network_retry_retains_tls_verification_and_changes_no_global_config(self):
        failed = subprocess.CompletedProcess([], 128, '', "fatal: unable to access 'https://github.com/example/repo': Recv failure")
        ok = subprocess.CompletedProcess([], 0, '', '')
        with patch.object(d.os, 'name', 'nt'), patch.object(d.subprocess, 'run', side_effect=[failed, ok]) as run, patch.object(d, 'log'):
            self.assertEqual(d.run_git(['git', 'pull', '--rebase', '--autostash']).returncode, 0)
        command = run.call_args_list[1].args[0]
        self.assertIn('http.sslBackend=openssl', command)
        self.assertIn('http.proxy=', command)
        self.assertNotIn('http.sslVerify=false', command)
        self.assertNotIn('--global', command)
        self.assertEqual(command[-3:], ['pull', '--rebase', '--autostash'])

    def test_git_conflict_is_not_retried_as_network_error(self):
        conflict = subprocess.CompletedProcess([], 1, '', 'error: Pulling is not possible because you have unmerged files.')
        with patch.object(d.os, 'name', 'nt'), patch.object(d.subprocess, 'run', return_value=conflict) as run:
            self.assertIs(d.run_git(['git', 'pull']), conflict)
        self.assertEqual(run.call_count, 1)

    def check_status(self, s3, pages, expected):
        ok = subprocess.CompletedProcess([], 0, '', '')
        with patch.object(d, 'sync_s3', return_value=s3), patch.object(d, 'sync_pages_repo', return_value=pages), \
                patch.object(d, 'run_git', return_value=ok), patch.object(d, 'git_stuck', return_value=None), \
                patch.object(d, 'alert_clear'), patch.object(d, 'alert_clear_all') as clear, patch.object(d, 'log'):
            result = d.publish_report('2026-11-08', True, None)
        self.assertEqual(result, expected)
        self.assertEqual(clear.called, expected == 0)

    def test_s3_failure_does_not_report_full_success(self):
        self.check_status(False, True, 4)

    def test_pages_failure_does_not_report_full_success(self):
        self.check_status(True, False, 4)

    def test_success_clears_alert_state(self):
        self.check_status(True, True, 0)

    def test_existing_pages_rebase_is_never_aborted(self):
        with patch.dict(d.CFG, {'pages_repo_dir': '/tmp/fake-pages'}), patch.object(d.os.path, 'isdir', return_value=True), \
                patch.object(d, 'git_stuck', return_value='rebase-merge'), patch.object(d, 'run_git') as git, \
                patch.object(d.subprocess, 'run') as process, patch.object(d, 'log'):
            self.assertFalse(d.sync_pages_repo('2026-11-10'))
        git.assert_not_called()
        process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
