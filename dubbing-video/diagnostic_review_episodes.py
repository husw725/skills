"""Two scoped review episodes; saved voices only, no cloning, source-bound receipts."""
import argparse
import copy
import math
from pathlib import Path
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from cartesia_pilot import bind, grouped_units, speech_request
from dub_episode import RATE, digest, probe, read_audio, run, trim_edges, write_audio, tts_request
from mflix_client import Mflix
from process_lock import process_lock
from repair_episode_feedback import generate
from screenplay_context import load_screenplay_context
from translate import read_json, save_json


def validate_config(cfg, n):
    if n not in (7, 29) or cfg['project_id'] != 59 or cfg['review_project_id'] != 148 or cfg.get('cloning_enabled') is not False:
        raise ValueError('Review pilot scope must be EP07/29 with cloning disabled')
    ep = cfg['episodes'][str(n)]
    for key, suffix in [('original_plan', 'dub-plan-v1.json'), ('source_subtitles', 'editorial/source.json'),
                        ('screenplay_context', 'editorial/screenplay-context.json'),
                        ('base_report', 'dub-v1/render-report.json'), ('subtitles', 'translation/translated.pt-BR.srt'),
                        ('output_dir', 'diagnostic-v2')]:
        if Path(ep[key]).resolve() != Path(f'output/drama-01/episode-{n:02}/{suffix}').resolve():
            raise ValueError('Pilot path outside episode scope')
    if ep['old_review_asset_id'] != {7: 2359, 29: 2381}[n]:
        raise ValueError('Unexpected Review parent')
    if ep['reuse_groups'] != ([] if n == 7 else ['e29-utterance-008']):
        raise ValueError('Unexpected reused group scope')
    return ep


def spoken_words(text):
    return [s.casefold() for s in re.findall(r'\w+', text, flags=re.UNICODE)]


def perform(cfg, n, mcp_config, ffmpeg):
    ep = validate_config(cfg, n)
    root = Path(ep['output_dir']); root.mkdir(parents=True, exist_ok=True)
    with process_lock(root/'production.lock', timeout=0):
        plan = read_json(ep['original_plan']); rows = read_json(ep['source_subtitles'])['segments']
        context = load_screenplay_context(ep['screenplay_context'], rows)
        if plan['episode'] != n or plan['project_id'] != 59:
            raise ValueError('Original plan scope differs')
        covered = [i for u in plan['units'] for i in u['cue_ids']]
        if len(covered) != len(rows) or len(set(covered)) != len(covered) or set(covered) != {r['id'] for r in rows}:
            raise ValueError('Source coverage differs')
        by_id = {r['id']: r for r in rows}
        for u in plan['units']:
            if len(u['cue_ids']) != 1:
                raise ValueError('Expected original single-cue units')
            row = by_id[u['cue_ids'][0]]
            if (u['text'], u['start'], u['end']) != (row['text'], row['start'], row['end']):
                raise ValueError('Source dialogue or original timecode changed')
        notes = context['episodes'][str(n)]['cue_annotations']
        for u in plan['units']:
            if u['screenplay_annotations'] != [notes[i] for i in u['cue_ids']]:
                raise ValueError('Plan screenplay evidence is stale')
        units = grouped_units(plan, ep['groups'])
        if set(ep['directions']) != {u['id'] for u in units}:
            raise ValueError('Missing production direction')
        for u in units:
            direction = ep['directions'][u['id']]
            if spoken_words(direction['text']) != spoken_words(u['translation']):
                raise ValueError('Only punctuation and case may change in synthesis text')
        storyboard = Path(cfg['storyboard']['path'])
        if digest(storyboard) != cfg['storyboard']['sha256']:
            raise ValueError('User storyboard version changed')
        assets = {k: Path(v) for k, v in plan['assets'].items()}
        hashes = {k: digest(v) for k, v in assets.items()}
        duration = float(probe(assets['video'], ffmpeg)['format']['duration'])
        cartesia = read_json('output/drama-01/cartesia-pilot-voices/voice-bank.json')
        minimax = read_json('output/drama-01/voice-bank.json')['voices']
        for u in units:
            if u['id'] in ep['reuse_groups']: continue
            direction = ep['directions'][u['id']]
            if direction['backend'] == 'cartesia':
                if u['production_voice'] not in cartesia or not cartesia[u['production_voice']]['voice_id'].startswith('cartesia:'):
                    raise ValueError('Saved Cartesia role voice missing')
            elif direction['backend'] == 'minimax':
                if u['production_voice'] not in minimax or direction['emotion'] not in (None, 'auto', 'fearful', 'calm', 'angry', 'sad', 'happy', 'disgusted', 'surprised', 'fluent'):
                    raise ValueError('Saved MiniMax role voice or emotion invalid')
            else:
                raise ValueError('Unexpected provider before paid work')
        base = read_json(ep['base_report'])
        original = {u['id']: u for u in base['utterances']}
        reused = {key: original[key] for key in ep['reuse_groups']}
        for key, u in reused.items():
            if digest(Path(u['fitted_path'])) != u['fitted_sha256']:
                raise ValueError('Uncertain source cue reuse changed')
        signature = bind(root/'input-fingerprint.json', {'config': cfg, 'episode': n,
             'plan_sha256': digest(Path(ep['original_plan'])), 'context_sha256': digest(Path(ep['screenplay_context'])),
             'source_sha256': digest(Path(ep['source_subtitles'])), 'subtitles_sha256': digest(Path(ep['subtitles'])),
             'asset_sha256': hashes, 'base_report_sha256': digest(Path(ep['base_report'])),
             'saved_cartesia_voices': cartesia, 'saved_minimax_voices': minimax, 'reused_audio': reused})
        client = Mflix(mcp_config)
        results = []
        for index, u in enumerate(units):
            direction = ep['directions'][u['id']]
            if u['id'] in reused:
                result = {**u, **copy.deepcopy(reused[u['id']]), 'generation_provider': 'v1-reused-uncertain-source',
                          'source_reader_verified': False, 'source_lexical_review_required': True}
                results.append(result)
                print('REUSE_UNCERTAIN_SOURCE', n, u['id'], flush=True)
                continue
            if direction['backend'] == 'cartesia':
                voice_id = cartesia[u['production_voice']]['voice_id']
                request = speech_request(direction['text'], voice_id, 59)
                emotion_applied = False
            elif direction['backend'] == 'minimax':
                voice_id = minimax[u['production_voice']]['voice_id']
                request = tts_request({**u, 'emotion': direction['emotion'] or 'auto',
                                       'translation': direction['text']}, voice_id, 59, 1.0, direction['emotion'] or 'auto')
                request.pop('referenceAudioList', None)
                request.update({'language': None, 'outputFormat': None})
                emotion_applied = direction['emotion'] is not None
            else:
                raise ValueError('Unexpected backend')
            folder = root/'utterances'/u['id']
            path, receipt = generate(client, request, folder)
            samples, leading, trailing = trim_edges(read_audio(path, ffmpeg))
            seconds = len(samples)/RATE
            next_start = units[index+1]['start'] if index+1 < len(units) else duration
            end_limit = max(u['end'], min(next_start-0.1, u['start']+seconds))
            target = end_limit-u['start']; factor = max(1.0, seconds/target)
            if factor > 1.25:
                raise ValueError('Excessive compression; inspect sample rather than blindly regenerate')
            trimmed, fitted = folder/'trimmed.wav', folder/'fitted.wav'
            write_audio(trimmed, samples)
            for _ in range(4):
                run([ffmpeg, '-v', 'error', '-y', '-i', trimmed, '-af', f'atempo={factor:.8f}',
                     '-ar', str(RATE), '-ac', '1', '-c:a', 'pcm_s16le', fitted])
                fitted_samples = read_audio(fitted, ffmpeg)
                if len(fitted_samples) <= math.floor(target*RATE): break
                factor *= len(fitted_samples)/(target*RATE)*1.005
            if factor > 1.25 or len(fitted_samples) > math.floor(target*RATE):
                raise ValueError('Cannot fit without excessive speedup or truncation')
            result = {**u, 'generation_provider': direction['backend'], 'voice_id': voice_id,
                      'synthesis_text': direction['text'], 'synthesis_request': request, 'task_id': receipt['task_id'],
                      'original_sha256': receipt['sha256'], 'natural_duration_seconds': seconds,
                      'atempo_factor': factor, 'audio_end_limit': end_limit,
                      'post_subtitle_gap_used_seconds': end_limit-u['end'],
                      'fitted_duration_seconds': len(fitted_samples)/RATE,
                      'fitted_path': str(fitted), 'fitted_sha256': digest(fitted),
                      'emotion_control_applied': emotion_applied, 'native_ptBR_listening_reviewed': False,
                      'speaker_audio_verified': False, 'performance_verified': False}
            save_json(folder/'result.json', result); results.append(result)
            save_json(root/'progress.json', {'status': 'synthesizing', 'episode': n,
                                           'completed': len(results), 'total': len(units)})
            print('COMPLETE', n, len(results), '/', len(units), flush=True)
        import numpy as np
        dialogue = np.zeros(math.ceil(duration*RATE), dtype=np.float32)
        for r in results:
            samples = read_audio(Path(r['fitted_path']), ffmpeg); start = round(r['start']*RATE)
            if start+len(samples) > len(dialogue): raise ValueError('Dialogue exceeds video')
            dialogue[start:start+len(samples)] += samples
        dialogue_file, mixed = root/'dialogue-ptBR.wav', root/'mix-ptBR.wav'
        write_audio(dialogue_file, dialogue)
        if {k: digest(v) for k, v in assets.items()} != hashes: raise ValueError('Source assets changed during pilot')
        run([ffmpeg, '-v', 'error', '-y', '-i', dialogue_file, '-i', assets['bgm'], '-i', assets['sfx'],
             '-filter_complex', f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[2:a]apad,atrim=duration={duration}[s];[d][b][s]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
             '-map', '[out]', '-ar', str(RATE), '-ac', '2', '-c:a', 'pcm_s16le', mixed])
        final = root/f'Carmilla_EP{n:02}_pt-BR_diagnostic_v2.mp4'
        run([ffmpeg, '-v', 'error', '-y', '-i', assets['video'], '-i', mixed, '-map', '0:v:0', '-map', '1:a:0',
             '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', final])
        run([ffmpeg, '-v', 'error', '-xerror', '-i', final, '-f', 'null', '-'])
        video_hashes = [run([ffmpeg, '-v', 'error', '-i', path, '-map', '0:v:0', '-c:v', 'copy', '-f', 'hash',
                           '-hash', 'sha256', '-']).strip() for path in (assets['video'], final)]
        if video_hashes[0] != video_hashes[1]: raise ValueError('Video payload changed')
        report = {'episode': n, 'status': 'rendered_diagnostic_candidate', 'route': cfg['route'],
                  'output': str(final), 'output_sha256': digest(final), 'video_payload_identical': True,
                  'duration_seconds': float(probe(final, ffmpeg)['format']['duration']),
                  'original_subtitles_sha256': digest(Path(ep['subtitles'])), 'source_audio_in_output': False,
                  'new_clone_count': 0, 'new_tts_task_count': len(units)-len(reused),
                  'reused_uncertain_source_groups': ep['reuse_groups'], 'native_ptBR_listening_reviewed': False,
                  'speaker_audio_verified': False, 'performance_verified': False, 'utterances': results,
                  'review_focus': ep['review_focus'], 'input_fingerprint': signature, 'completed_at': time.time()}
        save_json(root/'render-report.json', report); save_json(root/'progress.json', {'status': 'complete', 'episode': n})
        print('RENDERED', n, final, flush=True)


def main():
    p = argparse.ArgumentParser(); p.add_argument('config', type=Path)
    p.add_argument('--mcp-config', required=True, type=Path); p.add_argument('--ffmpeg', required=True, type=Path)
    a = p.parse_args()
    if sys.platform != 'win32': p.error('Business execution is Windows-only')
    cfg = read_json(a.config)
    for n in (7, 29): validate_config(cfg, n)
    def worker(n):
        try: perform(cfg, n, a.mcp_config, a.ffmpeg)
        except Exception as exc:
            if not str(exc).startswith('Another worker holds '):
                root = Path(cfg['episodes'][str(n)]['output_dir']); root.mkdir(parents=True, exist_ok=True)
                save_json(root/'progress.json', {'status': 'stopped', 'episode': n, 'reason': type(exc).__name__})
            print('STOPPED', n, type(exc).__name__, str(exc), flush=True)
            raise
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, n) for n in (7, 29)]
        for future in futures: future.result()


if __name__ == '__main__': main()
