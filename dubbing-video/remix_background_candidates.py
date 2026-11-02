"""Mix reviewed time-map candidates with immutable paid dialogue. No API calls."""
import argparse
import math
from pathlib import Path
import shutil
import sys
import time
import uuid

from dub_episode import digest, probe, run
from process_lock import process_lock
from translate import read_json, save_json


def bound(item):
    path = Path(item['path'])
    if digest(path) != item['sha256']:
        raise ValueError('Bound source changed')
    return path


def remix(row, root, ffmpeg):
    files = {key: bound(row[key]) for key in ('parent_report', 'picture', 'dialogue', 'subtitle',
                                             'background', 'mapping_evidence', 'separation_evidence')}
    parent = read_json(files['parent_report'])
    if parent['output_sha256'] != row['picture']['sha256'] or parent['subtitle_sha256'] != row['subtitle']['sha256']:
        raise ValueError('Parent delivery differs')
    shift = row['background_to_picture_seconds']
    if isinstance(shift, bool) or not isinstance(shift, (int, float)) or not math.isfinite(shift):
        raise ValueError('Time shift must be finite')
    meta = probe(files['picture'], ffmpeg)
    video = next(s for s in meta['streams'] if s['codec_type'] == 'video')
    duration = float(video.get('duration', meta['format']['duration']))
    bg_seconds = float(probe(files['background'], ffmpeg)['format']['duration'])
    overlap = max(0, min(duration, bg_seconds+shift)-max(0, shift))
    if overlap < duration-.1:
        raise ValueError('Constant map does not cover picture')
    attempt = root/f'attempt-{uuid.uuid4().hex}'
    attempt.mkdir(parents=True)
    aligned = attempt/'background-aligned.wav'
    # Positive shift delays the background; negative shift trims its leading audio.
    trim = max(0, -shift)
    delay_samples = round(max(0, shift)*48000)
    filt = f'aresample=48000,atrim=start={trim},asetpts=PTS-STARTPTS'
    if delay_samples:
        filt += f',adelay={delay_samples}S:all=1'
    filt += f',apad,atrim=duration={duration}'
    run([ffmpeg, '-nostdin', '-v', 'error', '-i', files['background'], '-af', filt,
         '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le', aligned])
    mix = attempt/'mix-pt-BR.wav'
    run([ffmpeg, '-nostdin', '-v', 'error', '-i', files['dialogue'], '-i', aligned,
         '-filter_complex', f'[0:a]apad,atrim=duration={duration}[d];[d][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
         '-map', '[out]', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', mix])
    final = attempt/f'The_Count_of_Monte_Cristo_EP{row["episode"]:02d}_pt-BR_background-candidate.mp4'
    run([ffmpeg, '-nostdin', '-v', 'error', '-i', files['picture'], '-i', mix,
         '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
         '-movflags', '+faststart', final])
    run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', final, '-f', 'null', '-'])
    hashes = [run([ffmpeg, '-nostdin', '-v', 'error', '-i', f, '-map', '0:v:0',
                   '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', '-']).strip() for f in (files['picture'], final)]
    if hashes[0] != hashes[1]:
        raise ValueError('Picture payload changed')
    if abs(float(probe(final, ffmpeg)['format']['duration'])-duration) > .15:
        raise ValueError('Candidate duration differs')
    subtitle = attempt/'pt-BR-production-candidate.srt'
    shutil.copyfile(files['subtitle'], subtitle)
    if digest(subtitle) != row['subtitle']['sha256']:
        raise ValueError('Copied subtitle differs')
    # Re-check immutable inputs after rendering too.
    for key in files:
        bound(row[key])
    report = {'episode': row['episode'], 'stage': 'background_remix_candidate', 'inputs': row,
              'output': str(final), 'output_sha256': digest(final), 'subtitle': str(subtitle),
              'subtitle_sha256': digest(subtitle), 'aligned_background': str(aligned),
              'aligned_background_sha256': digest(aligned), 'picture_payload_identical': True,
              'full_decode_passed': True, 'dialogue_reused_unchanged': True, 'new_tts': 0, 'new_clones': 0,
              'background_gain': 1, 'native_listening_passed': False, 'background_listening_passed': False,
              'residual_english_screened': False, 'published': False}
    save_json(attempt/'render-report.private.json', report)
    return {'status': 'candidate_rendered', 'report': str(attempt/'render-report.private.json'),
            'report_sha256': digest(attempt/'render-report.private.json')}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ffmpeg', type=Path, required=True)
    p.add_argument('--source-audit', type=Path, required=True)
    a = p.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Media operations run on Windows')
    data = read_json(a.manifest)
    eps = [r['episode'] for r in data['episodes']]
    if len(eps) != len(set(eps)) or not eps:
        raise ValueError('Duplicate or empty episode scope')
    audit = read_json(a.source_audit)
    if (audit.get('manifest_sha256') != digest(a.manifest)
        or audit.get('technical_source_chain_approved') is not True
        or set(audit.get('approved_episodes', [])) != set(eps)):
        raise ValueError('Independent source-chain audit missing or mismatched')
    a.output.mkdir(parents=True, exist_ok=True)
    progress = a.output/'progress.private.json'
    manifest_sha = digest(a.manifest)
    with process_lock(a.output/'remix.lock', timeout=0):
        state = read_json(progress) if progress.exists() else {'manifest_sha256': manifest_sha,
                 'source_audit_sha256': digest(a.source_audit), 'episodes': {}}
        if state['manifest_sha256'] != manifest_sha or state['source_audit_sha256'] != digest(a.source_audit):
            raise ValueError('Prior remix scope changed')
        for row in data['episodes']:
            key = str(row['episode'])
            old = state['episodes'].get(key)
            if old and old['status'] == 'candidate_rendered':
                bound({'path': old['report'], 'sha256': old['report_sha256']})
                report = read_json(old['report'])
                if report['inputs'] != row:
                    raise ValueError('Completed candidate inputs differ')
                for name in ('parent_report', 'picture', 'dialogue', 'subtitle', 'background',
                             'mapping_evidence', 'separation_evidence'):
                    bound(row[name])
                bound({'path': report['output'], 'sha256': report['output_sha256']})
                bound({'path': report['subtitle'], 'sha256': report['subtitle_sha256']})
                continue
            state['episodes'][key] = {'status': 'running'}
            save_json(progress, state)
            try:
                state['episodes'][key] = remix(row, a.output/f'episode-{int(key):02d}', a.ffmpeg)
            except Exception as e:
                state['episodes'][key] = {'status': 'failed', 'error_type': type(e).__name__}
            save_json(progress, state)
            print('BACKGROUND_REMIX', key, state['episodes'][key]['status'], flush=True)
        state['finished_at'] = time.time()
        save_json(progress, state)


if __name__ == '__main__':
    main()
