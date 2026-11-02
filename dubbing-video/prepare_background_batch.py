"""Separate hash-bound scored sources locally; no synthesis, mixing or publishing."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from dub_episode import digest, run, probe
from process_lock import process_lock
from translate import save_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mapping', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ffmpeg', type=Path, required=True)
    p.add_argument('--episodes', type=int, nargs='+', required=True)
    a = p.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Source preparation runs on Windows')
    checkpoint = Path.home()/'.cache/torch/hub/checkpoints/955717e8-8726e21a.th'
    model_sha = digest(checkpoint)
    if not model_sha.startswith('8726e21a'):
        raise ValueError('Pinned cached model missing or changed')
    mapping_sha = digest(a.mapping)
    recipe = {'model': 'htdemucs', 'model_sha256': model_sha, 'shifts': 0,
              'overlap': 0.25, 'segment': 7, 'device': 'cpu', 'float32': True}
    rows = json.loads(a.mapping.read_text(encoding='utf-8'))['episodes']
    chosen = [r for r in rows if r['episode'] in a.episodes]
    if len(chosen) != len(set(a.episodes)) or {r['episode'] for r in chosen} != set(a.episodes):
        raise ValueError('Episode mapping incomplete or duplicated')
    a.output.mkdir(parents=True, exist_ok=True)
    progress = a.output/'progress.private.json'
    env = {**os.environ, 'OMP_NUM_THREADS': '6', 'MKL_NUM_THREADS': '6', 'PYTHONIOENCODING': 'utf-8'}
    with process_lock(a.output/'batch.lock', timeout=0):
        state = {'stage': 'source_separation_only', 'mapping_sha256': mapping_sha,
                 'started_at': time.time(), 'episodes': {}, 'new_tts': 0, 'new_clones': 0,
                 'mixing_completed': False, 'listening_passed': False, 'published': False}
        for row in chosen:
            ep = row['episode']
            root = a.output/f'episode-{ep:02d}'
            root.mkdir(parents=True, exist_ok=True)
            receipt = root/'receipt.private.json'
            item = {'status': 'running', 'source': row['regular_source'], 'model_sha256': model_sha,
                    'recipe': recipe}
            state['episodes'][str(ep)] = item
            save_json(progress, state)
            try:
                src = Path(row['regular_source']['path'])
                if digest(src) != row['regular_source']['sha256']:
                    raise ValueError('Source SHA changed')
                if receipt.exists():
                    old = json.loads(receipt.read_text(encoding='utf-8'))
                    if old['source'] != item['source'] or old.get('recipe') != recipe:
                        raise ValueError('Existing separation identity changed')
                    if any(digest(f['path']) != f['sha256'] for f in old['stems']):
                        raise ValueError('Existing separated audio changed')
                    item.update(status='complete', reused=True)
                else:
                    wav = root/'source-stereo.wav'
                    extraction = root/'extraction.private.json'
                    if wav.exists():
                        proof = json.loads(extraction.read_text(encoding='utf-8'))
                        if proof['source_sha256'] != digest(src) or proof['wav_sha256'] != digest(wav):
                            raise ValueError('Existing extracted audio changed')
                    else:
                        part = root/f'extract-{uuid.uuid4().hex}.wav'
                        run([a.ffmpeg, '-nostdin', '-v', 'error', '-i', src, '-vn',
                             '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', part])
                        part.rename(wav)
                        save_json(extraction, {'source_sha256': digest(src), 'wav_sha256': digest(wav)})
                    source_probe = probe(src, a.ffmpeg)
                    source_audio = next(s for s in source_probe['streams'] if s['codec_type'] == 'audio')
                    source_seconds = float(source_audio.get('duration', source_probe['format']['duration']))
                    attempt = root/f'attempt-{uuid.uuid4().hex}'
                    attempt.mkdir()
                    cmd = [sys.executable, '-m', 'demucs', '-n', 'htdemucs', '--two-stems',
                           'vocals', '--shifts', '0', '--overlap', '0.25', '--segment', '7',
                           '-d', 'cpu', '--float32', '-j', '0', '-o', str(attempt/'stems'), str(wav)]
                    item['attempt'] = str(attempt)
                    save_json(progress, state)
                    with (attempt/'separation.log').open('wb') as log:
                        subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       check=True, timeout=900)
                    stems = [attempt/'stems/htdemucs/source-stereo'/n for n in ('vocals.wav', 'no_vocals.wav')]
                    for f in [wav, *stems]:
                        run([a.ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', f, '-f', 'null', '-'])
                        info = probe(f, a.ffmpeg)
                        audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
                        seconds = float(audio.get('duration', info['format']['duration']))
                        if abs(seconds-source_seconds) > 0.1 or int(audio['sample_rate']) != 44100 or audio['channels'] != 2:
                            raise ValueError('Separated or extracted audio duration/format differs')
                    item.update(status='complete', stems=[{'path': str(f), 'sha256': digest(f)} for f in stems])
                    save_json(receipt, item)
            except Exception as e:
                item.update(status='failed', error_type=type(e).__name__)
            save_json(progress, state)
            print('BACKGROUND_SOURCE', ep, item['status'], flush=True)
        state.update(finished_at=time.time(), status='complete' if all(
            i['status'] == 'complete' for i in state['episodes'].values()) else 'needs_attention')
        save_json(progress, state)


if __name__ == '__main__':
    main()
