"""Windows EP02 repair: two protected paid submissions, all other audio reused."""
import argparse
import copy
import math
from pathlib import Path
import sys
import time

from cartesia_pilot import bind, download
from dub_episode import RATE, digest, probe, read_audio, run, safe_submit, trim_edges, write_audio
from mflix_client import Mflix
from process_lock import process_lock
from translate import read_json, save_json

TARGETS = {'e02-utterance-016': ['e02-16'], 'e02-utterance-018': ['e02-18']}


def validate_config(cfg):
    for k, expected in {
        'base_report': 'output/drama-01/episode-02/cartesia-v2-pilot/render-report.json',
        'output_dir': 'output/drama-01/episode-02/feedback-v3',
        'voice_bank': 'output/drama-01/voice-bank.json',
        'screenplay_context': 'output/drama-01/episode-02/editorial/screenplay-context.json',
    }.items():
        if Path(cfg[k]).resolve() != Path(expected).resolve():
            raise ValueError('Unexpected repair path: '+k)
    if (cfg['episode'], cfg['project_id'], cfg['review_project_id'], cfg['old_review_asset_id']) != (2, 59, 148, 2478):
        raise ValueError('Unexpected repair scope')
    if cfg['voice_role'] != 'Laura' or set(cfg['patches']) != set(TARGETS):
        raise ValueError('Only two Laura cries may be repaired')
    for key, patch in cfg['patches'].items():
        if patch['cue_ids'] != TARGETS[key] or patch['emotion'] != 'fearful' or patch['speed'] != 1.0:
            raise ValueError('Unexpected repair request')
        if not isinstance(patch['synthesis_text'], str) or not patch['synthesis_text'].strip():
            raise ValueError('Missing phonetic synthesis input')


def request_for(text, voice_id, project_id):
    if voice_id.startswith('cartesia:'):
        raise ValueError('Repair must use the existing MiniMax role voice')
    return {'projectId': project_id, 'model': 'speech-2.8-hd', 'text': text,
            'voiceId': voice_id, 'languageBoost': 'Portuguese', 'emotion': 'fearful',
            'speed': 1.0, 'vol': 1.0, 'pitch': 0, 'format': 'wav',
            'language': None, 'outputFormat': None, 'duration': None,
            'prompt': None, 'referenceVideoList': []}


def generate(client, request, folder):
    folder.mkdir(parents=True, exist_ok=True)
    bind(folder/'request-fingerprint.json', request)
    accepted = safe_submit(client, 'generateAudio', {'request': request}, folder/'submission.private.json')
    state_file = folder/'task.private.json'
    result = read_json(state_file) if state_file.exists() else {}
    last = 0
    while result.get('taskStatus') not in (2, 3):
        delay = max(0, 10-(time.time()-last))
        if delay:
            time.sleep(delay)
        last = time.time()
        result = client.task(accepted['taskId'])
        save_json(state_file, result)
        print('TASK', accepted['taskId'], result.get('taskStatus'), flush=True)
    if result['taskStatus'] != 2:
        raise ValueError('Repair synthesis failed; do not automatically retry paid task')
    url = result.get('resultAudioUrl') or (result.get('resultAudioUrls') or [None])[0]
    original = folder/'original.wav'
    download(client, url, original)
    receipt_file = folder/'audio-receipt.json'
    receipt = {'task_id': accepted['taskId'], 'sha256': digest(original)}
    if receipt_file.exists() and read_json(receipt_file) != receipt:
        raise ValueError('Downloaded repair audio differs')
    save_json(receipt_file, receipt)
    return original, receipt


def execute(cfg, config_path, mcp_config, ffmpeg):
    validate_config(cfg)
    root = Path(cfg['output_dir'])
    root.mkdir(parents=True, exist_ok=True)
    with process_lock(root/'repair.lock', timeout=0):
        base_path = Path(cfg['base_report'])
        if digest(base_path) != cfg['base_report_sha256']:
            raise ValueError('Base v2 report changed')
        base = read_json(base_path)
        if base['episode'] != 2 or base['model'] != 'sonic-3.6' or len(base['utterances']) != 17:
            raise ValueError('Unexpected base episode')
        plan_path = Path('output/drama-01/episode-02/dub-plan-v1.json')
        plan = read_json(plan_path)
        bank = read_json(cfg['voice_bank'])
        voice_id = bank['voices']['Laura']['voice_id']
        context = read_json(cfg['screenplay_context'])
        source_path = Path('output/drama-01/episode-02/editorial/source.json')
        from screenplay_context import load_screenplay_context
        load_screenplay_context(cfg['screenplay_context'], read_json(source_path)['segments'])
        coverage = [i for r in base['utterances'] for i in r['cue_ids']]
        if len(coverage) != 25 or set(coverage) != {f'e02-{n}' for n in range(1, 26)}:
            raise ValueError('Base cue coverage differs')
        for row in base['utterances']:
            if digest(Path(row['fitted_path'])) != row['fitted_sha256']:
                raise ValueError('Base fitted audio changed')
            if row['id'] in TARGETS:
                note = context['episodes']['2']['cue_annotations'][row['cue_ids'][0]]
                if row['production_voice'] != 'Laura' or note['speaker'] != 'Laura' or note['emotion_intent'] != 'fearful':
                    raise ValueError('Repair speaker or screenplay intent differs')
        signature = bind(root/'input-fingerprint.json', {'config': cfg, 'base_sha256': digest(base_path),
                         'plan_sha256': digest(plan_path), 'context_sha256': digest(Path(cfg['screenplay_context'])),
                         'voice_id': voice_id, 'source_sha256': digest(source_path),
                         'base_audio_hashes': [r['fitted_sha256'] for r in base['utterances']]})
        client = Mflix(mcp_config)
        results = []
        for index, row in enumerate(base['utterances']):
            r = copy.deepcopy(row)
            if r['id'] not in TARGETS:
                r['generation_provider'] = 'cartesia-v2-reused'
                results.append(r)
                continue
            patch = cfg['patches'][r['id']]
            original, receipt = generate(client, request_for(patch['synthesis_text'], voice_id, cfg['project_id']),
                                         root/'patches'/r['id'])
            samples, leading, trailing = trim_edges(read_audio(original, ffmpeg))
            seconds = len(samples)/RATE
            next_start = base['utterances'][index+1]['start'] if index+1 < len(base['utterances']) else base['duration_seconds']
            audio_end = max(r['end'], min(next_start-0.1, r['start']+seconds))
            target = audio_end-r['start']
            factor = max(1.0, seconds/target)
            if factor > 1.25:
                raise ValueError('Repair would need excessive speedup; retain sample for inspection')
            folder = original.parent
            trimmed, fitted = folder/'trimmed.wav', folder/'fitted.wav'
            write_audio(trimmed, samples)
            for _ in range(4):
                run([ffmpeg, '-v', 'error', '-y', '-i', trimmed, '-af', f'atempo={factor:.8f}',
                     '-ar', str(RATE), '-ac', '1', '-c:a', 'pcm_s16le', fitted])
                fitted_samples = read_audio(fitted, ffmpeg)
                if len(fitted_samples) <= math.floor(target*RATE):
                    break
                factor *= len(fitted_samples)/(target*RATE)*1.005
            if factor > 1.25 or len(fitted_samples) > math.floor(target*RATE):
                raise ValueError('Repair cannot fit without excessive acceleration or truncation')
            r.update({'generation_provider': 'minimax-feedback-patch', 'model': 'speech-2.8-hd',
                      'voice_id': voice_id, 'synthesis_text': patch['synthesis_text'],
                      'synthesis_request': request_for(patch['synthesis_text'], voice_id, cfg['project_id']),
                      'task_id': receipt['task_id'], 'original_sha256': receipt['sha256'],
                      'natural_duration_seconds': seconds, 'atempo_factor': factor,
                      'fitted_path': str(fitted), 'fitted_sha256': digest(fitted),
                      'fitted_duration_seconds': len(fitted_samples)/RATE,
                      'audio_end_limit': audio_end, 'post_subtitle_gap_used_seconds': audio_end-r['end'],
                      'trimmed_leading_seconds': leading, 'trimmed_trailing_seconds': trailing,
                      'emotion_control_applied': True, 'requested_emotion': 'fearful',
                      'scream_verified': False, 'phonetic_control_verified': False,
                      'native_ptBR_listening_reviewed': False, 'timing_quality_review_required': False})
            save_json(folder/'result.json', r)
            results.append(r)
        import numpy as np
        assets = {k: Path(v) for k, v in plan['assets'].items()}
        duration = float(probe(assets['video'], ffmpeg)['format']['duration'])
        dialogue = np.zeros(math.ceil(duration*RATE), dtype=np.float32)
        for r in results:
            samples = read_audio(Path(r['fitted_path']), ffmpeg)
            start = round(r['start']*RATE)
            if start+len(samples) > len(dialogue):
                raise ValueError('Audio past video')
            dialogue[start:start+len(samples)] += samples
        dialogue_file = root/'dialogue-ptBR.wav'
        write_audio(dialogue_file, dialogue)
        # Readback must be identical to v2 outside both old and new patch extents.
        before = read_audio(base_path.parent/'dialogue-ptBR.wav', ffmpeg)
        after = read_audio(dialogue_file, ffmpeg)
        if len(before) != len(after):
            raise ValueError('Dialogue timeline length changed')
        mask = np.ones(len(before), dtype=bool)
        for old, new in zip(base['utterances'], results):
            if old['id'] in TARGETS:
                end = max(old['start']+old['fitted_duration_seconds'], new['start']+new['fitted_duration_seconds'])
                mask[round(old['start']*RATE):math.ceil(end*RATE)+2] = False
        if not np.array_equal(before[mask], after[mask]):
            raise ValueError('Unrelated dialogue samples changed')
        mixed = root/'mix-ptBR.wav'
        run([ffmpeg, '-v', 'error', '-y', '-i', dialogue_file, '-i', assets['bgm'], '-i', assets['sfx'],
             '-filter_complex', f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[2:a]apad,atrim=duration={duration}[s];[d][b][s]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
             '-map', '[out]', '-ar', str(RATE), '-ac', '2', '-c:a', 'pcm_s16le', mixed])
        final = root/'Carmilla_EP02_pt-BR_feedback_v3.mp4'
        run([ffmpeg, '-v', 'error', '-y', '-i', assets['video'], '-i', mixed, '-map', '0:v:0',
             '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', final])
        run([ffmpeg, '-v', 'error', '-xerror', '-i', final, '-f', 'null', '-'])
        hashes = [run([ffmpeg, '-v', 'error', '-i', path, '-map', '0:v:0', '-c:v', 'copy',
                       '-f', 'hash', '-hash', 'sha256', '-']).strip() for path in (assets['video'], final)]
        if hashes[0] != hashes[1]:
            raise ValueError('Video payload changed')
        report = {'episode': 2, 'status': 'rendered_feedback_candidate',
                  'provider': 'Cartesia v2 plus two MiniMax feedback patches',
                  'output': str(final), 'output_sha256': digest(final),
                  'duration_seconds': float(probe(final, ffmpeg)['format']['duration']),
                  'base_report_sha256': cfg['base_report_sha256'], 'input_fingerprint': signature,
                  'video_payload_identical': True, 'source_audio_in_output': False,
                  'unchanged_dialogue_outside_patch_extents': True,
                  'original_subtitles_sha256': base['original_subtitles_sha256'],
                  'patched_units': sorted(TARGETS), 'reused_unit_count': 15,
                  'new_clone_count': 0, 'new_tts_task_count': 2,
                  'native_ptBR_listening_reviewed': False, 'scream_verified': False,
                  'comment_timestamp_mapping_verified': False,
                  'utterances': results, 'completed_at': time.time()}
        save_json(root/'render-report.json', report)
        save_json(root/'progress.json', {'status': 'complete'})
        print('RENDERED', final, report['output_sha256'], flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('config', type=Path)
    p.add_argument('--mcp-config', required=True, type=Path)
    p.add_argument('--ffmpeg', required=True, type=Path)
    a = p.parse_args()
    if sys.platform != 'win32':
        p.error('Business execution is Windows-only')
    cfg = read_json(a.config)
    validate_config(cfg)
    try:
        execute(cfg, a.config, a.mcp_config, a.ffmpeg)
    except Exception as exc:
        if not str(exc).startswith('Another worker holds '):
            root = Path(cfg['output_dir'])
            root.mkdir(parents=True, exist_ok=True)
            save_json(root/'progress.json', {'status': 'stopped', 'reason': type(exc).__name__})
        print('STOPPED', type(exc).__name__, str(exc), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
