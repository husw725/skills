"""Render separately versioned alignment candidates from pinned, already paid speech."""
import argparse
import copy
import re
from pathlib import Path
import sys
import time
import numpy as np

from dub_episode import RATE, digest, probe, read_audio, run, trim_edges, write_audio
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
import generate_monte_episode01 as speech
import fit_render_monte_episode01 as fitting


def store(path, value):
    if path.exists():
        if read_json(path) != value: raise ValueError('Preserve differing prior alignment evidence')
    else:
        save_json(path, value)


def checked_parent(entry):
    root = Path(entry['parent_root'])
    plan = read_json(root/'speech-plan.private.json')
    generated = read_json(root/'generation-result.private.json')
    if (digest(root/'speech-plan.private.json') != entry['parent_plan_sha256']
            or digest(root/'generation-result.private.json') != entry['parent_generation_sha256']
            or plan['project_id'] != 100 or plan['episode'] != entry['episode']
            or plan.get('holds') or generated['plan_sha256'] != entry['parent_plan_sha256']
            or [g['id'] for g in plan['groups']] != [r['group_id'] for r in generated['groups']]):
        raise ValueError('Pinned complete parent episode required')
    for path, sha in plan['inputs_sha256'].items():
        if digest(path) != sha: raise ValueError('Original episode source changed')
    for group, row in zip(plan['groups'], generated['groups']):
        cache = Path('output/review-project-100/paid-speech-cache')/group['cache_key']
        if ((cache/'raw-receipt.prepared.private.json').exists()
                or (Path(row['raw_path']).parent/'raw-receipt.prepared.private.json').exists()):
            raise ValueError('Interrupted paid receipt must be reconciled separately; alignment is read-only')
        request, task, receipt = speech.read_cache(cache,
                                                 group['cache_key'], group['request'])
        if (receipt is None or task != row['task_id'] or row['key'] != group['cache_key']
                or row['raw_sha256'] != receipt['sha256'] or digest(row['raw_path']) != row['raw_sha256']):
            raise ValueError('Existing paid speech differs from successful immutable cache')
    return root, plan, generated


def joint_groups(groups, joins):
    result = copy.deepcopy(groups)
    for join in joins:
        ids = join['ids']
        if not 2 <= len(ids) <= 4: raise ValueError('Bounded complete-thought join required')
        indices = [next(i for i, g in enumerate(result) if g['id'] == key) for key in ids]
        if indices != list(range(indices[0], indices[0]+len(ids))):
            raise ValueError('Only adjacent groups can form one complete thought')
        rows = result[indices[0]:indices[-1]+1]
        identity = {(g['role'], g['delivery_mode'], g['request']['emotion'],
                     g['request']['voiceId'], g['request']['speed']) for g in rows}
        if len(identity) != 1 or not join['source_context_evidence'].strip():
            raise ValueError('Never join different roles, modes, emotions, or voices')
        if join['id'] in {g['id'] for g in result}: raise ValueError('New derivative group ID required')
        first = rows[0]
        merged = {'id': join['id'], 'role': first['role'], 'delivery_mode': first['delivery_mode'],
                  'cue_ids': [cue for g in rows for cue in g['cue_ids']],
                  'unit_ids': [unit for g in rows for unit in g['unit_ids']],
                  'text': ' '.join(g['text'] for g in rows), 'start': first['start'], 'end': rows[-1]['end'],
                  'request': {'speed': first['request']['speed'], 'emotion': first['request']['emotion'],
                              'voiceId': first['request']['voiceId'], 'derived_cached_audio_only': True},
                  'source_group_ids': ids, 'source_context_evidence': join['source_context_evidence'],
                  'join_pause_seconds': .08}
        merged['cache_key'] = 'derived:'+fingerprint(merged)
        result[indices[0]:indices[-1]+1] = [merged]
    if [cue for g in result for cue in g['cue_ids']] != [cue for g in groups for cue in g['cue_ids']]:
        raise ValueError('Original cue order and coverage must survive alignment')
    return result


def repair(entry, recipe_path, recipe_sha, ffmpeg):
    parent_root, old, generated = checked_parent(entry)
    root = Path(entry['output_root'])
    if (root.is_symlink() or root.resolve() == parent_root.resolve() or not re.fullmatch(r'alignment-candidate-20261101-v[1-3]', root.name)
            or root.resolve().parent != parent_root.resolve().parent):
        raise ValueError('Separate immutable episode candidate directory required')
    root.mkdir(exist_ok=True)
    with process_lock(root/'alignment.lock', timeout=0):
        by_id = {r['group_id']: r for r in generated['groups']}
        groups = joint_groups(old['groups'], entry.get('joins', []))
        placements = entry.get('placements', {})
        if not set(placements) <= {g['id'] for g in groups}: raise ValueError('Placement outside episode')
        for g in groups:
            if g['id'] in placements:
                if not placements[g['id']]['source_context_evidence'].strip(): raise ValueError('Placement evidence required')
                g['original_source_start'] = g['start']
                g['start'] = placements[g['id']].get('start', g['start'])
        if any(g['start'] < 0 for g in groups) or any(a['start'] >= b['start'] for a, b in zip(groups, groups[1:])):
            raise ValueError('Chronological speech order must remain unchanged')
        rows = []
        for g in groups:
            if 'source_group_ids' not in g:
                rows.append(copy.deepcopy(by_id[g['id']]))
                continue
            sources = [by_id[key] for key in g['source_group_ids']]
            folder = root/g['id']; folder.mkdir(exist_ok=True)
            binding = {'parent_generation_sha256': entry['parent_generation_sha256'], 'sources': sources,
                       'join_pause_seconds': .08, 'recipe_sha256': recipe_sha}
            store(folder/'binding.private.json', binding)
            wav = folder/'joined.wav'; receipt = folder/'receipt.private.json'
            if receipt.exists():
                raw = read_json(receipt)
                if raw['binding_sha256'] != digest(folder/'binding.private.json') or digest(wav) != raw['raw_sha256']:
                    raise ValueError('Derivative audio changed')
            else:
                if wav.exists(): raise ValueError('Orphan derivative WAV; inspect without overwriting')
                pieces = []
                for i, source in enumerate(sources):
                    if i: pieces.append(np.zeros(round(.08*RATE), dtype=np.float32))
                    pieces.append(trim_edges(read_audio(Path(source['raw_path']), ffmpeg))[0])
                write_audio(wav, np.concatenate(pieces))
                raw = {'group_id': g['id'], 'key': g['cache_key'], 'raw_path': str(wav), 'raw_sha256': digest(wav),
                       'seconds': len(np.concatenate(pieces))/RATE, 'binding_sha256': digest(folder/'binding.private.json'),
                       'source_task_ids': [r['task_id'] for r in sources], 'derived_from_paid_audio': True,
                       'new_submission_attempts': 0}
                save_json(receipt, raw)
            rows.append(raw)
        plan = {**old, 'groups': groups, 'max_new_tts': 0, 'new_clone_count': 0,
                'alignment_candidate_only': True, 'source_picture_alignment_verified': False,
                'inputs_sha256': {**old['inputs_sha256'], str(recipe_path): recipe_sha,
                                 str(parent_root/'speech-plan.private.json'): entry['parent_plan_sha256'],
                                 str(parent_root/'generation-result.private.json'): entry['parent_generation_sha256']}}
        for row in rows: plan['inputs_sha256'][row['raw_path']] = row['raw_sha256']
        store(root/'speech-plan.private.json', plan)
        store(root/'generation-result.private.json', {'plan_sha256': digest(root/'speech-plan.private.json'),
              'groups': rows, 'new_clone_count': 0, 'native_listening_passed': False, 'new_submission_attempts': 0})
        subtitle = root/'pt-BR-production-candidate.srt'
        if subtitle.exists() and subtitle.read_text(encoding='utf-8') != plan['subtitle_text']:
            raise ValueError('Original production subtitles must stay unchanged')
        if not subtitle.exists(): subtitle.write_text(plan['subtitle_text'], encoding='utf-8')
        report_path = root/'render-report.private.json'
        if report_path.exists():
            report = read_json(report_path)
            if report['plan_sha256'] != digest(root/'speech-plan.private.json') or digest(report['output']) != report['output_sha256']:
                raise ValueError('Existing candidate video changed')
            return {'episode': entry['episode'], 'stage': 'alignment_candidate_rendered', 'root': str(root)}
        duration = float(probe(Path(plan['media']['video']), ffmpeg)['format']['duration'])
        fit = {'plan_sha256': digest(root/'speech-plan.private.json'),
               'generation_sha256': digest(root/'generation-result.private.json'),
               'media_sha256': {p: digest(p) for p in plan['media'].values()}, 'groups': [], 'blocked': [],
               'new_tts': 0, 'new_clones': 0, 'native_listening_passed': False,
               'source_picture_alignment_verified': False}
        for i, (g, raw) in enumerate(zip(groups, rows)):
            next_start = groups[i+1]['start'] if i+1 < len(groups) else duration+.08
            cap = placements.get(g['id'], {}).get('end_limit', g['end']+.8)
            end = min(cap, next_start-.08, duration)
            audio, left, right = trim_edges(read_audio(Path(raw['raw_path']), ffmpeg))
            available = end-g['start']; natural = len(audio)/RATE
            tempo = max(1., natural/available) if available > 0 else float('inf')
            if tempo > 1.2+1e-8:
                fit['blocked'].append({'id': g['id'], 'raw_seconds': natural, 'available_seconds': available}); continue
            folder = root/'fitted'/g['id']; folder.mkdir(parents=True, exist_ok=True)
            binding = {'raw_sha256': raw['raw_sha256'], 'plan_sha256': fit['plan_sha256'],
                       'start': g['start'], 'end_limit': end, 'post_atempo': tempo}
            store(folder/'input.private.json', binding)
            target = folder/'fitted.wav'; receipt = folder/'receipt.private.json'
            if receipt.exists():
                value = read_json(receipt)
                if value['input_fingerprint'] != fingerprint(binding) or digest(target) != value['sha256']:
                    raise ValueError('Existing alignment audio changed')
            else:
                if target.exists(): raise ValueError('Orphan fitted preview; preserve it')
                trimmed = folder/'trimmed.wav'
                if trimmed.exists(): raise ValueError('Interrupted trim requires reconciliation')
                write_audio(trimmed, audio)
                run([ffmpeg, '-nostdin', '-v', 'error', '-n', '-i', trimmed, '-af', f'atempo={tempo:.12f}',
                     '-ar', str(RATE), '-ac', '1', '-c:a', 'pcm_s16le', target])
                actual = float(probe(target, ffmpeg)['format']['duration'])
                value = {'id': g['id'], 'path': str(target), 'sha256': digest(target), 'start': g['start'],
                         'seconds': actual, 'source_display_end': g['end'], 'end_limit': end,
                         'synthesis_speed': g['request']['speed'], 'post_atempo': tempo,
                         'nominal_combined_rate': g['request']['speed']*tempo,
                         'edge_trim_seconds': [left, right], 'input_fingerprint': fingerprint(binding)}
                save_json(receipt, value)
            if value['start']+value['seconds'] > end+.02:
                fit['blocked'].append({'id': g['id'], 'reason': 'Actual filtered duration exceeds available space'}); continue
            fit['groups'].append(value)
        for a, b in zip(fit['groups'], fit['groups'][1:]):
            if a['start']+a['seconds'] > b['start']-.06:
                fit['blocked'].append({'id': a['id'], 'reason': 'Actual adjacent voice guard failed'})
        save_json(root/'fit-report.private.json', fit)
        save_json(root/'progress.private.json', {'stage': 'timing_review' if fit['blocked'] else 'alignment_render_pending',
                  'blocked': fit['blocked'], 'new_tts': 0, 'new_clones': 0})
        if fit['blocked']: return {'episode': entry['episode'], 'stage': 'timing_review', 'blocked': fit['blocked']}
        fitting.ROOT = root
        fitting.render(plan, fit, ffmpeg, (Path(plan['media']['video']), Path(plan['media']['background'])),
                       f'project100_EP{entry["episode"]:02d}_pt-BR_alignment_candidate.mp4')
        return {'episode': entry['episode'], 'stage': 'alignment_candidate_rendered', 'root': str(root)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe', type=Path, required=True); p.add_argument('--recipe-sha256', required=True)
    p.add_argument('--ffmpeg', type=Path, required=True)
    args = p.parse_args()
    if sys.platform != 'win32': raise ValueError('Windows media processing only')
    if digest(args.recipe) != args.recipe_sha256: raise ValueError('Reviewed recipe changed')
    recipe = read_json(args.recipe)
    if (recipe['project_id'] != 100 or recipe['new_tts'] != 0 or recipe['new_clones'] != 0
            or not 1 <= len(recipe['episodes']) <= 15): raise ValueError('Bounded zero-TTS recipe required')
    if digest(recipe['audit_report_path']) != recipe['audit_report_sha256']: raise ValueError('Audit evidence changed')
    root = args.recipe.parent
    with process_lock(root/'alignment-batch.lock', timeout=0):
        results = []
        for entry in recipe['episodes']:
            try: result = repair(entry, args.recipe, args.recipe_sha256, args.ffmpeg)
            except Exception as exc:
                result = {'episode': entry['episode'], 'stage': 'needs_reconciliation', 'error_type': type(exc).__name__,
                          'error': str(exc)[:300]}
            results.append(result)
            save_json(root/'alignment-batch-progress.private.json', {'results': results, 'total': len(recipe['episodes']),
                      'new_tts': 0, 'new_clones': 0, 'updated_at': time.time()})
            print('CACHED_ALIGNMENT', result['episode'], result['stage'], flush=True)


if __name__ == '__main__': main()
