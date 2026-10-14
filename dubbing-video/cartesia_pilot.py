"""Windows-only Cartesia pilot; isolated receipts, one submission per speech group."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from dub_episode import (RATE, digest, probe, read_audio, run, safe_submit,
                         trim_edges, validate_units, write_audio)
from mflix_client import Mflix
from process_lock import process_lock
from translate import fingerprint, read_json, save_json


def speech_request(text, voice_id, project_id):
    if not voice_id.startswith('cartesia:'):
        raise ValueError('Cartesia voice namespace required')
    return {'projectId': project_id, 'model': 'sonic-3.6', 'text': text,
            'voiceId': voice_id, 'language': 'pt-BR', 'speed': 1.0,
            'outputFormat': 'wav', 'format': None, 'emotion': None,
            'languageBoost': None, 'pitch': None, 'prompt': None,
            'duration': None, 'referenceVideoList': [], 'vol': None}


def bind(path, value):
    expected = fingerprint(value)
    if path.exists():
        if read_json(path)['fingerprint'] != expected:
            raise ValueError('Pilot inputs changed; inspect receipts before continuing')
    else:
        save_json(path, {'fingerprint': expected})
    return expected


def grouped_units(plan, groups):
    by_id = {u['id']: u for u in plan['units']}
    result = []
    covered = []
    for ids in groups:
        rows = [by_id[i] for i in ids]
        if len({u['production_voice'] for u in rows}) != 1:
            raise ValueError('Cannot group different speakers')
        positions = [next(i for i, u in enumerate(plan['units']) if u['id'] == row['id']) for row in rows]
        if positions != list(range(positions[0], positions[0]+len(positions))):
            raise ValueError('Cannot group across intervening source dialogue')
        if any(a['end'] > b['start'] for a, b in zip(rows, rows[1:])):
            raise ValueError('Group must be chronological and non-overlapping')
        result.append({'id': ids[0], 'source_unit_ids': ids,
                       'cue_ids': [i for u in rows for i in u['cue_ids']],
                       'production_voice': rows[0]['production_voice'],
                       'start': rows[0]['start'], 'end': rows[-1]['end'],
                       'translation': ' '.join(u['translation'] for u in rows),
                       'source_windows': [{'id': u['id'], 'start': u['start'],
                                           'end': u['end']} for u in rows],
                       'script_intents': [u['emotion'] for u in rows]})
        covered.extend(ids)
    if covered != [u['id'] for u in plan['units']]:
        raise ValueError('Grouping must cover every original unit once in original order')
    return result


def download(client, url, path):
    if not isinstance(url, str) or not url.startswith('https://'):
        raise ValueError('Expected HTTPS generated audio')
    if path.exists():
        return
    for attempt in range(3):
        try:
            r = client.http.get(url, timeout=120)
            r.raise_for_status()
            if r.headers.get('Content-Length') and len(r.content) != int(r.headers['Content-Length']):
                raise ValueError('Incomplete audio download')
            temporary = path.with_suffix('.download.part')
            temporary.write_bytes(r.content)
            temporary.replace(path)
            return
        except Exception:
            if attempt == 2:
                raise RuntimeError('Audio download failed; paid task receipt retained') from None
            time.sleep(2 ** attempt)


def generate(client, text, voice_id, project_id, folder):
    folder.mkdir(parents=True, exist_ok=True)
    request = speech_request(text, voice_id, project_id)
    bind(folder/'request-fingerprint.json', request)
    submitted = safe_submit(client, 'generateAudio', {'request': request}, folder/'submission.private.json')
    task_id = submitted['taskId']
    state_file = folder/'task.private.json'
    result = read_json(state_file) if state_file.exists() else {}
    last_poll = 0
    while result.get('taskStatus') not in (2, 3):
        delay = max(0, 10 - (time.time() - last_poll))
        if delay:
            time.sleep(delay)
        last_poll = time.time()
        result = client.task(task_id)
        save_json(state_file, result)
        print('TASK', task_id, result.get('taskStatus'), flush=True)
    if result['taskStatus'] != 2:
        raise RuntimeError('Cartesia task failed; inspect saved receipt; no paid retry')
    url = result.get('resultAudioUrl') or (result.get('resultAudioUrls') or [None])[0]
    path = folder/'original.wav'
    download(client, url, path)
    record = {'task_id': task_id, 'request_fingerprint': fingerprint(request),
              'voice_id': voice_id, 'language': 'pt-BR', 'sha256': digest(path)}
    saved = folder/'audio-receipt.json'
    if saved.exists() and read_json(saved) != record:
        raise ValueError('Downloaded audio differs from prior receipt')
    save_json(saved, record)
    return path, record


def voices(client, cfg, ffmpeg):
    bank_dir = Path(cfg['voice_bank_dir'])
    bank_dir.mkdir(parents=True, exist_ok=True)
    with process_lock(bank_dir/'bank.lock', timeout=0):
        bank = {}
        for role, reference in cfg['references'].items():
            path = Path(reference['path'])
            if digest(path) != reference['sha256']:
                raise ValueError('Reference audio changed')
            if path.stat().st_size > 16*1024*1024:
                raise ValueError('Reference exceeds Cartesia upload limit')
            seconds = float(probe(path, ffmpeg)['format']['duration'])
            if seconds < 10 or seconds > 60:
                raise ValueError('Use a 10–60 second pilot reference')
            key = fingerprint({'project_id': cfg['project_id'], 'platform': 'cartesia', 'role': role})
            folder = bank_dir/key
            folder.mkdir(exist_ok=True)
            bind(folder/'reference-fingerprint.json', {'project_id': cfg['project_id'],
                 'platform': 'cartesia', 'role': role, 'reference_sha256': reference['sha256']})
            url_file = folder/'upload.private.json'
            if not url_file.exists():
                save_json(url_file, {'url': client.upload(path)})
            request = {'platform': 'cartesia', 'projectId': cfg['project_id'],
                       'referenceAudioUrl': read_json(url_file)['url'],
                       'name': 'Carmilla pilot '+role,
                       'remark': 'EP02 pt-BR pilot; reuse this saved voice; native listening pending'}
            bind(folder/'clone-request-fingerprint.json', request)
            response = safe_submit(client, 'uploadVoice', {'request': request}, folder/'clone.private.json')
            voice_id = response.get('voiceId')
            if not isinstance(voice_id, str) or not voice_id.startswith('cartesia:'):
                raise ValueError('Unexpected clone response; do not submit another clone')
            bank[role] = {'voice_id': voice_id, 'reference_sha256': reference['sha256'],
                          'reference_seconds': seconds, 'speaker_audio_verified': False,
                          'native_ptBR_listening_reviewed': False,
                          'accent_support': response.get('accents', 'unknown')}
            save_json(bank_dir/'voice-bank.json', bank)
            print('VOICE_READY', role, voice_id, flush=True)
            if role == cfg['smoke_role']:
                generate(client, cfg['smoke_text'], voice_id, cfg['project_id'], Path(cfg['output_dir'])/'smoke')
        return bank


def execute(args):
    cfg = read_json(args.config)
    if cfg['episode'] != 2 or cfg['project_id'] != 59 or cfg['review_project_id'] != 148:
        raise ValueError('This pilot is scoped to Carmilla EP02 and its existing Review project')
    root = Path(cfg['output_dir'])
    root.mkdir(parents=True, exist_ok=True)
    with process_lock(root/'pilot.lock', timeout=0):
        plan = read_json(cfg['original_plan'])
        if plan['episode'] != cfg['episode'] or plan['project_id'] != cfg['project_id']:
            raise ValueError('Original plan scope differs')
        assets = {k: Path(v) for k, v in plan['assets'].items()}
        duration = float(probe(assets['video'], args.ffmpeg)['format']['duration'])
        validate_units(plan['units'], plan['voices'], duration)
        from screenplay_context import load_screenplay_context
        rows = read_json(cfg['source_subtitles'])['segments']
        context = load_screenplay_context(cfg['screenplay_context'], rows)
        rows_by_id = {r['id']: r for r in rows}
        for u in plan['units']:
            if len(u['cue_ids']) != 1 or rows_by_id[u['cue_ids'][0]]['text'] != u['text']:
                raise ValueError('Pilot original dialogue differs from reviewed source')
            row = rows_by_id[u['cue_ids'][0]]
            if row['start'] != u['start'] or row['end'] != u['end']:
                raise ValueError('Pilot original timecode changed')
        units = grouped_units(plan, cfg['groups'])
        source_signature = bind(root/'input-fingerprint.json', {'config': cfg, 'plan': plan,
            'source_sha256': {k: digest(p) for k, p in assets.items()},
            'source_subtitles_sha256': digest(Path(cfg['source_subtitles'])),
            'context_sha256': digest(Path(cfg['screenplay_context'])),
            'subtitles_sha256': digest(Path(cfg['subtitles'])), 'policy': 'cartesia-pilot-v1'})
        client = Mflix(args.mcp_config)
        bank = voices(client, cfg, args.ffmpeg)
        print('SMOKE_COMPLETE', flush=True)
        results = []
        for u in units:
            folder = root/'utterances'/u['id']
            original, receipt = generate(client, u['translation'], bank[u['production_voice']]['voice_id'],
                                         cfg['project_id'], folder)
            samples, leading, trailing = trim_edges(read_audio(original, args.ffmpeg))
            measured = len(samples)/RATE
            target = u['end']-u['start']
            factor = max(1.0, measured/target)
            trimmed = folder/'trimmed.wav'
            fitted = folder/'fitted.wav'
            write_audio(trimmed, samples)
            run([args.ffmpeg, '-v', 'error', '-y', '-i', trimmed, '-af', f'atempo={factor:.8f}',
                 '-ar', str(RATE), '-ac', '1', '-c:a', 'pcm_s16le', fitted])
            fitted_samples = read_audio(fitted, args.ffmpeg)
            # FFmpeg's tempo filter has boundary rounding. Refit rather than cut speech.
            for _ in range(3):
                if len(fitted_samples) <= math.ceil(target*RATE):
                    break
                factor *= len(fitted_samples)/(target*RATE)*1.005
                run([args.ffmpeg, '-v', 'error', '-y', '-i', trimmed, '-af', f'atempo={factor:.8f}',
                     '-ar', str(RATE), '-ac', '1', '-c:a', 'pcm_s16le', fitted])
                fitted_samples = read_audio(fitted, args.ffmpeg)
            if len(fitted_samples) > math.ceil(target*RATE):
                raise ValueError('Audio still exceeds group window; do not truncate words')
            record = {**u, **receipt, 'atempo_factor': factor, 'natural_duration_seconds': measured,
                      'fitted_path': str(fitted), 'fitted_sha256': digest(fitted),
                      'trimmed_leading_seconds': leading, 'trimmed_trailing_seconds': trailing,
                      'timing_quality_review_required': factor > 1.25,
                      'emotion_control_applied': False}
            save_json(folder/'result.json', record)
            results.append(record)
            save_json(root/'progress.json', {'status': 'synthesizing', 'completed': len(results),
                      'total': len(units), 'updated_at': time.time()})
            print('COMPLETE_GROUP', len(results), '/', len(units), flush=True)
        import numpy as np
        dialogue = np.zeros(math.ceil(duration*RATE), dtype=np.float32)
        for r in results:
            samples = read_audio(Path(r['fitted_path']), args.ffmpeg)
            start = round(r['start']*RATE)
            if start+len(samples) > len(dialogue):
                raise ValueError('Audio beyond video')
            dialogue[start:start+len(samples)] += samples
        dialogue_file = root/'dialogue-ptBR.wav'
        mixed = root/'mix-ptBR.wav'
        write_audio(dialogue_file, dialogue)
        run([args.ffmpeg, '-v', 'error', '-y', '-i', dialogue_file, '-i', assets['bgm'], '-i', assets['sfx'],
             '-filter_complex', f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[2:a]apad,atrim=duration={duration}[s];[d][b][s]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
             '-map', '[out]', '-ar', str(RATE), '-ac', '2', '-c:a', 'pcm_s16le', mixed])
        final = root/'Carmilla_EP02_pt-BR_Cartesia_v2.mp4'
        run([args.ffmpeg, '-v', 'error', '-y', '-i', assets['video'], '-i', mixed, '-map', '0:v:0',
             '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', final])
        run([args.ffmpeg, '-v', 'error', '-xerror', '-i', final, '-f', 'null', '-'])
        hashes = [run([args.ffmpeg, '-v', 'error', '-i', p, '-map', '0:v:0', '-c:v', 'copy',
                       '-f', 'hash', '-hash', 'sha256', '-']).strip() for p in (assets['video'], final)]
        if hashes[0] != hashes[1]:
            raise ValueError('Video payload changed')
        report = {'episode': 2, 'status': 'rendered_pilot', 'provider': 'cartesia', 'model': 'sonic-3.6',
                  'requested_language': 'pt-BR', 'video_payload_identical': True,
                  'source_audio_in_output': False, 'output': str(final), 'output_sha256': digest(final),
                  'duration_seconds': float(probe(final, args.ffmpeg)['format']['duration']),
                  'original_subtitles_sha256': digest(Path(cfg['subtitles'])),
                  'native_ptBR_listening_reviewed': False, 'speaker_audio_verified': False,
                  'emotion_control_applied': False, 'voices': bank, 'utterances': results,
                  'timing_quality_review_count': sum(r['timing_quality_review_required'] for r in results),
                  'input_fingerprint': source_signature, 'completed_at': time.time()}
        save_json(root/'render-report.json', report)
        save_json(root/'progress.json', {'status': 'complete', 'completed': len(results), 'total': len(units)})
        print('RENDERED', final, 'timing_review', report['timing_quality_review_count'], flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('config', type=Path)
    p.add_argument('--mcp-config', required=True, type=Path)
    p.add_argument('--ffmpeg', required=True, type=Path)
    args = p.parse_args()
    if sys.platform != 'win32':
        p.error('Business execution is Windows-only')
    try:
        execute(args)
    except Exception as exc:
        root = Path(read_json(args.config)['output_dir'])
        root.mkdir(parents=True, exist_ok=True)
        if not str(exc).startswith('Another worker holds '):
            save_json(root/'progress.json', {'status': 'stopped', 'reason': type(exc).__name__, 'updated_at': time.time()})
        print('STOPPED', type(exc).__name__, str(exc), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
