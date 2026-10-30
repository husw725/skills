"""Bounded local supervision; only an interrupted offline ASR task may restart."""
import json
from pathlib import Path
import subprocess
import sys
import time
from process_lock import process_lock
from dub_episode import digest
from translate import read_json, save_json

ROOT = Path('output/four-dramas-20261030/supervision')
ASR_TASK = 'Codex-FourDramas-SeriesSourceEvidence-20261030'
EDITORIAL_TASK = 'Codex-MonteCristo-Episode01-Editorial-20261030'
OFFLINE_WORKER_SHA = '520cb3f57aea18021a397ff74c299722758ea9319753e4dc042e272b711f355f'


def task_state(name):
    if name not in (ASR_TASK, EDITORIAL_TASK):
        raise ValueError('Unexpected scheduled task')
    command = ("$t=Get-ScheduledTask -TaskName '" + name + "'; "
        "$p=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -like '*prepare_review_series_asr.py*'}); "
        "[pscustomobject]@{State=$t.State;Actions=@($t.Actions | Select-Object Execute,Arguments,WorkingDirectory);OfflineProcesses=$p.Count} | ConvertTo-Json -Depth 5 -Compress")
    result = subprocess.run(['powershell', '-NoProfile', '-Command', command],
        capture_output=True, text=True, timeout=25, check=True)
    return json.loads(result.stdout)


def inspect():
    now = time.time()
    path = ROOT / 'window.private.json'
    if not path.exists():
        save_json(path, {'started_at': now, 'expires_at': now + 48 * 3600})
    window = read_json(path)
    prior_path = ROOT / 'recovery.private.json'
    recovery = read_json(prior_path) if prior_path.exists() else {'attempts': []}
    health = {'checked_at': now, 'expires_at': window['expires_at'],
        'expired': now >= window['expires_at'], 'automatic_voice_requests': False,
        'automatic_text_requests': False, 'alerts': []}
    paths = {'source_asr': Path('output/four-dramas-20261030/series-source-asr/progress.private.json'),
        'episode_text': Path('output/review-project-100/episode-01/editorial-candidate-20261030/progress.private.json')}
    states = {name: read_json(path) if path.exists() else {} for name, path in paths.items()}
    for name, task in [('source_asr', ASR_TASK), ('episode_text', EDITORIAL_TASK)]:
        state = states[name]
        snapshot = task_state(task)
        live = snapshot['State']
        health[name] = {'task_state': live, 'stage': state.get('stage'),
            'updated_at': state.get('updated_at')}
        if name == 'source_asr':
            done = len(state.get('completed', {}))
            health[name]['completed'] = done
            health[name]['total'] = state.get('total')
            complete = state.get('stage') == 'source_evidence_complete_review_pending' and done == 136 and not state.get('errors')
            if complete:
                continue
            if state.get('errors'):
                health['alerts'].append('source_asr_errors_need_review')
            elif live != 4:
                attempts = recovery['attempts']
                actions=snapshot['Actions']
                expected_args='prepare_review_series_asr.py --ffmpeg "D:\\Program Files\\ffmpeg\\ffmpeg-master-latest-win64-gpl-shared\\bin\\ffmpeg.exe"'
                approved=(len(actions)==1
                    and Path(actions[0]['Execute'])==Path('output/tools/asr-venv/Scripts/python.exe').resolve()
                    and Path(actions[0]['WorkingDirectory'])==Path.cwd()
                    and actions[0]['Arguments']==expected_args
                    and digest('prepare_review_series_asr.py')==OFFLINE_WORKER_SHA
                    and snapshot['OfflineProcesses']==0)
                safe = (approved and live == 3 and not health['expired'] and state.get('total') == 136
                    and state.get('stage') == 'preparing_series_source_evidence'
                    and 0 <= done < 136 and len(attempts) < 2
                    and all(x.get('status') == 'start_requested' for x in attempts))
                if safe:
                    # Record intent before starting; an ambiguous scheduler result is never retried.
                    attempt = {'time': now, 'task': ASR_TASK, 'status': 'start_pending_reconciliation'}
                    attempts.append(attempt)
                    save_json(prior_path, recovery)
                    try:
                        result = subprocess.run(['powershell', '-NoProfile', '-Command',
                            "Start-ScheduledTask -TaskName '" + ASR_TASK + "'"],
                            capture_output=True, text=True, timeout=25)
                    except subprocess.TimeoutExpired:
                        health['alerts'].append('offline_recovery_pending_scheduler_timeout')
                    else:
                        if result.returncode == 0:
                            attempt['status'] = 'start_requested'
                            save_json(prior_path, recovery)
                        else:
                            health['alerts'].append('offline_recovery_requires_reconciliation')
                else:
                    health['alerts'].append('source_asr_stopped_needs_review')
        elif live != 4 and state.get('stage') != 'text_candidate_ready_independent_review_pending':
            health['alerts'].append('editorial_stopped_no_automatic_resubmission')
        if live == 4 and now - state.get('updated_at', now) > 2400:
            health['alerts'].append(name + '_progress_stale_needs_review_no_kill')
    save_json(ROOT / 'health.private.json', health)
    with (ROOT / 'history.private.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(health, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    if sys.platform != 'win32':
        raise ValueError('Windows scheduled-task supervision only')
    ROOT.mkdir(parents=True, exist_ok=True)
    with process_lock(ROOT / 'supervisor.lock', timeout=0):
        inspect()
