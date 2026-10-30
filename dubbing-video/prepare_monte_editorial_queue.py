"""Finite original-subtitle text candidates for Monte Cristo EP02–32, no voice API."""
from pathlib import Path
import hashlib
import subprocess
import sys
import time
from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json, fingerprint

ROOT = Path('output/review-project-100/editorial-queue-20261031')


def validate_artifacts(episode,folder):
    """Read-only audit of the saved version; never submit a new text request."""
    import prepare_review_episode_editorial as worker
    worker.configure_episode(episode)
    if worker.ROOT!=folder:raise ValueError('Unexpected editorial candidate location')
    context=read_json(folder/'source-input.private.json');signature=fingerprint(context)
    result=read_json(folder/'editorial-result.private.json')
    if (context['episode']!=episode
      or read_json(folder/'source-fingerprint.private.json')['fingerprint']!=signature):
        raise ValueError('Saved episode input snapshot changed')
    worker.validate_completed(result,context['timed_source'],context,signature)
    expected=hashlib.sha256(worker.candidate_srt(context['timed_source'],result['candidate'])).hexdigest()
    if result['subtitle_sha256']!=expected or digest(folder/'pt-BR-candidate.srt')!=expected:
        raise ValueError('Candidate SRT differs from original saved cues')
    return result


def main():
    if sys.platform != 'win32':
        raise ValueError('Run business preparation on Windows')
    ROOT.mkdir(parents=True, exist_ok=True)
    with process_lock(ROOT / 'queue.lock', timeout=0):
        path = ROOT / 'progress.private.json'
        state = read_json(path) if path.exists() else {'episodes': {},
            'scope': list(range(2, 33)), 'voice_generation_started': False}
        if (state['scope'] != list(range(2, 33)) or state['voice_generation_started'] is not False
          or not set(state['episodes']).issubset({str(n) for n in range(2,33)})):
            raise ValueError('Finite text-only queue scope changed')
        for episode in state['scope']:
            key = str(episode)
            folder = Path(f'output/review-project-100/episode-{episode:02d}/editorial-candidate-20261031')
            result = folder / 'editorial-result.private.json'
            subtitle = folder / 'pt-BR-candidate.srt'
            prior = state['episodes'].get(key)
            if prior:
                if prior['status'] == 'text_candidate_ready':
                    if digest(result) != prior['result_sha256'] or digest(subtitle) != prior['subtitle_sha256']:
                        raise ValueError('Prior candidate changed; preserve queue')
                    validate_artifacts(episode,folder)
                # Failed or interrupted text work is preserved for explicit reconciliation.
                continue
            state.update(stage='preparing_text_candidates', current_episode=episode, updated_at=time.time())
            state['episodes'][key] = {'status': 'running_needs_reconciliation_if_interrupted'}
            save_json(path, state)
            with (ROOT / f'episode-{episode:02d}.private.log').open('a', encoding='utf-8') as stream:
                try:
                    process = subprocess.Popen([sys.executable, 'prepare_review_episode_editorial.py',
                        '--episode', str(episode)], stdout=stream, stderr=stream)
                except OSError as exc:
                    state['episodes'][key]={'status':'start_failed_needs_review','error_type':type(exc).__name__,'automatic_retry':False}
                    state['updated_at']=time.time();save_json(path,state)
                    continue
                try:
                    returncode = process.wait(timeout=1500)
                except subprocess.TimeoutExpired:
                    state['episodes'][key] = {'status': 'timeout_needs_reconciliation', 'automatic_retry': False}
                    state['updated_at'] = time.time();save_json(path, state)
                    try:
                        killed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,timeout=25)
                        if killed.returncode!=0:raise ValueError('Child termination failed')
                        process.wait(timeout=25)
                    except (OSError,subprocess.TimeoutExpired,ValueError):
                        raise ValueError('Child process termination uncertain; stop queue') from None
                    state['episodes'][key]['child_termination_confirmed']=True;save_json(path,state)
                    continue
            if returncode == 0 and result.exists() and subtitle.exists():
                data = validate_artifacts(episode,folder)
                if (data['candidate']['episode'] != episode
                        or data['candidate']['project_id'] != 100
                        or any(data[k] is not False for k in ('independent_editorial_approved',
                            'source_video_versions_matched', 'audio_speaker_verified',
                            'native_listening_passed', 'tts_ready'))
                        or digest(subtitle) != data['subtitle_sha256']):
                    raise ValueError('Worker result scope or approval state changed')
                state['episodes'][key] = {'status': 'text_candidate_ready',
                    'result_sha256': digest(result), 'subtitle_sha256': digest(subtitle)}
            else:
                state['episodes'][key] = {'status': 'needs_review_no_automatic_retry', 'exit_code': returncode}
            state['updated_at'] = time.time()
            save_json(path, state)
        ready = sum(e['status'] == 'text_candidate_ready' for e in state['episodes'].values())
        state.update(stage='text_candidates_ready_independent_review_pending' if ready == 31
            else 'text_candidates_partial_need_review', ready=ready, updated_at=time.time())
        save_json(path, state)


if __name__ == '__main__':
    main()
