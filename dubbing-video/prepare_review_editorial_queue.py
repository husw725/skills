"""Persistent finite per-drama screenplay-based text queue; never creates voices."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import time

from dub_episode import digest
from process_lock import process_lock
from translate import fingerprint, read_json, save_json

COUNTS = {96: 30, 110: 35, 102: 37, 100: 32}
FALSE_FLAGS = ('independent_editorial_approved', 'source_video_versions_matched',
               'audio_speaker_verified', 'native_listening_passed', 'tts_ready')


def folder_for(project, episode):
    revision = '20261030' if project == 100 and episode == 1 else '20261031'
    return Path(f'output/review-project-{project}/episode-{episode:02d}/editorial-candidate-{revision}')


def current_context(project, episode):
    import prepare_review_episode_editorial as worker
    context_worker = worker.context_worker
    manifest = read_json(context_worker.ROOT / 'intake-manifest.private.json')
    if fingerprint(manifest) != context_worker.MANIFEST_FINGERPRINT:
        raise ValueError('Source collection changed')
    context = context_worker.inputs(project, manifest)
    bible_folder = Path(f'output/review-project-{project}/translation-context-candidate-20261030')
    bible = read_json(bible_folder / 'context-candidate.private.json')
    context_worker.validate_result(bible, context, fingerprint(context), bible_folder)
    from review_episode_source import episode_rows
    rows, evidence = episode_rows(project, episode)
    if evidence is not None:
        context['machine_source_evidence'] = evidence
        context['timed_source_kind'] = evidence['kind']
    context['series_context'] = bible['candidate']
    context['series_context_sha256'] = digest(bible_folder / 'context-candidate.private.json')
    context['timed_source'] = rows
    context['episode'] = episode
    context['quality_policy'] = read_json(Path('ptbr_quality_policy.json'))
    context['quality_policy_sha256'] = digest('ptbr_quality_policy.json')
    return context


def check_basis(saved, current):
    if fingerprint(saved) != fingerprint(current):
        raise ValueError('Current source, screenplay, ASR, context, or policy differs from saved basis')


def validate_saved(project, episode, folder):
    with process_lock(folder / 'editorial.lock', timeout=0):
        return validate_saved_locked(project, episode, folder)


def validate_saved_locked(project, episode, folder):
    import prepare_review_episode_editorial as worker
    worker.configure_episode(episode, project)
    if worker.ROOT != folder:
        raise ValueError('Unexpected candidate path')
    context = read_json(folder / 'source-input.private.json')
    check_basis(context, current_context(project, episode))
    signature = fingerprint(context)
    result = read_json(folder / 'editorial-result.private.json')
    if (context['episode'] != episode
        or read_json(folder / 'source-fingerprint.private.json')['fingerprint'] != signature):
        raise ValueError('Saved source fingerprint differs')
    worker.validate_completed(result, context['timed_source'], context, signature)
    expected = hashlib.sha256(worker.candidate_srt(context['timed_source'], result['candidate'])).hexdigest()
    if (result['candidate']['project_id'] != project or result['candidate']['episode'] != episode
        or any(result[flag] is not False for flag in FALSE_FLAGS)
        or result['subtitle_sha256'] != expected or digest(folder / 'pt-BR-candidate.srt') != expected):
        raise ValueError('Candidate scope, SRT, or approval changed')
    return {'status': 'text_candidate_ready', 'result_sha256': digest(folder / 'editorial-result.private.json'),
            'subtitle_sha256': expected, 'cue_count': len(result['candidate']['cues'])}


def step(project, episode, prior, validator=validate_saved, runner=None):
    """Use verified outputs before any child launch; ambiguous attempts never resubmit."""
    folder = folder_for(project, episode)
    if (folder / 'editorial-result.private.json').exists():
        ready = validator(project, episode, folder)
        if prior:
            if any(key in prior and prior[key] != ready[key] for key in ('result_sha256', 'subtitle_sha256')):
                raise ValueError('Previously recorded candidate changed')
        return ready
    if prior:
        return {**prior, 'status': 'needs_reconciliation', 'automatic_retry': False}
    if runner is None:
        raise ValueError('No explicit runner')
    code = runner(project, episode)
    if code != 0:
        return {'status': 'needs_reconciliation', 'exit_code': code, 'automatic_retry': False}
    return validator(project, episode, folder)


def terminate_child(process):
    try:
        killed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                capture_output=True, timeout=25)
        if killed.returncode != 0:
            raise RuntimeError('Child termination uncertain; stop this queue')
        process.wait(timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Child termination uncertain; stop this queue') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=int, choices=tuple(COUNTS), required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Production text queue runs on Windows')
    project = args.project
    root = Path(f'output/review-project-{project}/continuous-editorial-queue-20261031')
    root.mkdir(parents=True, exist_ok=True)
    with process_lock(root / 'queue.lock', timeout=0):
        path = root / 'progress.private.json'
        state = read_json(path) if path.exists() else {'project_id': project,
            'scope': list(range(1, COUNTS[project] + 1)), 'episodes': {}, 'voice_generation_started': False}
        if (state['project_id'] != project or state['scope'] != list(range(1, COUNTS[project]+1))
            or state['voice_generation_started'] is not False
            or not set(state['episodes']).issubset({str(n) for n in state['scope']})):
            raise ValueError('Queue scope changed')

        def persist():
            state['updated_at'] = time.time()
            state['ready'] = sum(row['status'] == 'text_candidate_ready' for row in state['episodes'].values())
            save_json(path, state)

        def run_child(pid, episode):
            key = str(episode)
            state['episodes'][key] = {'status': 'submission_reserved', 'started_at': time.time()}
            persist()  # A crash before/after launch requires reconciliation, never blind re-submit.
            with (root / f'episode-{episode:02d}.private.log').open('a', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, '-u', 'prepare_review_episode_editorial.py',
                    '--project', str(pid), '--episode', str(episode)], stdout=log, stderr=log)
                state['episodes'][key].update(status='running', child_pid=process.pid)
                persist()
                started = time.monotonic()
                while True:
                    try:
                        return process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        state['heartbeat_at'] = time.time()
                        persist()
                        if time.monotonic()-started > 1500:
                            state['episodes'][key].update(status='timeout_needs_reconciliation', automatic_retry=False)
                            persist()
                            terminate_child(process)
                            return 124

        for episode in state['scope']:
            key = str(episode)
            state.update(stage='translating_with_screenplay', current_episode=episode)
            prior = state['episodes'].get(key)
            persist()
            try:
                state['episodes'][key] = step(project, episode, prior, runner=run_child)
            except RuntimeError:
                state.update(stage='blocked_child_termination_uncertain');persist()
                raise
            except Exception as exc:
                state['episodes'][key] = {**state['episodes'].get(key, {}), 'status': 'needs_reconciliation',
                    'error_type': type(exc).__name__, 'automatic_retry': False}
                # Full traceback is private; one failed episode does not stop independent episodes.
                import traceback
                with (root / f'episode-{episode:02d}.private.log').open('a', encoding='utf-8') as log:
                    traceback.print_exc(file=log)
            persist()
        state['stage'] = ('all_text_candidates_ready_independent_review_pending'
                          if state['ready'] == COUNTS[project] else 'partial_text_candidates_need_reconciliation')
        state['finished_at'] = time.time()
        persist()


if __name__ == '__main__':
    main()
