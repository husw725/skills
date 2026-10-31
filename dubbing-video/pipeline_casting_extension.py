"""Fill explicitly reviewed held cues using saved voices; never clone or replace paid speech."""
import argparse
import copy
from pathlib import Path
import sys

from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
import pipeline_speech as pipeline
import generate_monte_episode01 as speech
import fit_render_monte_episode01 as fitting


def pinned(path, sha):
    path = Path(path)
    if digest(path) != sha:
        raise ValueError('Casting extension evidence changed')
    return read_json(path)


def pin_file(path, sha):
    if digest(path) != sha:
        raise ValueError('Casting audit file changed')


def reused_voices(path, project, roles, inputs):
    manifest = read_json(path)
    if (manifest['project_id'] != project or manifest['new_clones'] != 0
            or manifest['reuse_authorized'] is not True
            or manifest['native_listening_passed'] is not False):
        raise ValueError('Explicit saved-voice reuse authorization required')
    pin_file(manifest['audit_report_path'], manifest['audit_report_sha256'])
    inputs[str(path)] = digest(path)
    inputs[manifest['audit_report_path']] = manifest['audit_report_sha256']
    bank = {}
    for role in roles:
        item = manifest['voices'][role]
        source = item['source_project_id']
        if source not in (96, 100, 102, 110) or (source == project and role != item['source_role']):
            raise ValueError('Saved voice source outside reviewed cross-drama bank')
        source_path = Path(f'output/review-project-{source}/pipeline-voices-20261031/voice-bank.private.json')
        entry = read_json(source_path)['voices'][item['source_role']]
        if fingerprint(entry) != item['source_entry_fingerprint']:
            raise ValueError('Source voice bank entry changed')
        proof = {}
        actual = pipeline.voice_bank(source, {item['source_role']}, proof)[item['source_role']]
        if actual != {'voice_id': item['voice_id'], 'platform': 'minimax'}:
            raise ValueError('Saved MiniMax voice differs from original clone receipts')
        inputs.update(proof)
        bank[role] = actual
    return bank


def preserved_groups(old, new):
    old_by_id = {g['id']: g for g in old}
    if len(old_by_id) != len(old) or len({g['id'] for g in new}) != len(new):
        raise ValueError('Unique original and added group IDs required')
    retained = [g for g in new if g['id'] in old_by_id]
    if retained != old:
        raise ValueError('Paid groups changed or reordered')
    additions = [g for g in new if g['id'] not in old_by_id]
    if not additions or {g['cache_key'] for g in old} & {g['cache_key'] for g in additions}:
        raise ValueError('Only distinct first-generation additions allowed')
    return additions


def build(decision_path):
    decision = read_json(decision_path)
    ext = decision['casting_extension']
    project, episode = decision['project_id'], decision['episode']
    if project != 100 or decision.get('production_revision') != 2:
        raise ValueError('Bounded Count first casting extension only')
    parent_path = Path(ext['parent_decision_path'])
    parent = pinned(parent_path, ext['parent_decision_sha256'])
    if parent.get('casting_extension') or parent.get('production_revision', 1) != 1:
        raise ValueError('No chained or cyclic paid extension')
    root = pipeline.audio_root(parent_path, parent)
    if (root/'render-report.private.json').exists():
        raise ValueError('Never replace an already rendered episode')
    old = pinned(root/'speech-plan.private.json', ext['parent_plan_sha256'])
    generated = pinned(root/'generation-result.private.json', ext['parent_generation_sha256'])
    if (old != pipeline.build(parent_path)
            or (old['project_id'], old['episode']) != (project, episode)
            or generated['plan_sha256'] != ext['parent_plan_sha256']
            or [r['group_id'] for r in generated['groups']] != [g['id'] for g in old['groups']]):
        raise ValueError('Original paid plan or generation scope changed')
    inputs = copy.deepcopy(old['inputs_sha256'])
    for p in (decision_path, parent_path, root/'speech-plan.private.json', root/'generation-result.private.json'):
        inputs[str(p)] = digest(p)
    pin_file(decision['audit_report_path'], decision['audit_report_sha256'])
    inputs[decision['audit_report_path']] = decision['audit_report_sha256']
    for g, row in zip(old['groups'], generated['groups']):
        _, task, receipt = speech.read_cache(Path(f'output/review-project-{project}/paid-speech-cache')/g['cache_key'], g['cache_key'], g['request'])
        if (receipt is None or task != row['task_id'] or row['key'] != g['cache_key']
                or receipt['sha256'] != row['raw_sha256'] or digest(row['raw_path']) != row['raw_sha256']):
            raise ValueError('Previously paid audio must be complete; never submit it again')
        inputs[row['raw_path']] = row['raw_sha256']
    if (decision['baseline_result_sha256'] != parent['baseline_result_sha256']
            or decision['source_input_sha256'] != parent['source_input_sha256']
            or decision['media_receipt_path'] != parent['media_receipt_path']
            or decision.get('production_candidate_path') != parent.get('production_candidate_path')):
        raise ValueError('Casting extension cannot change text or source media')
    original = {u['id']: u for u in parent['units']}
    retained = [u for u in decision['units'] if u['id'] in original]
    if retained != parent['units']:
        raise ValueError('Original paid units changed')
    additions = [u for u in decision['units'] if u['id'] not in original]
    source = read_json(Path(next(p for p in old['inputs_sha256'] if p.endswith('source-input.private.json'))))
    candidate = {'cues': old['production_cues']}
    pipeline.checked_units(source['timed_source'], candidate, decision)
    held = {h['cue_id']: h for h in parent['holds']}
    added_cues = {u['cue_id'] for u in additions}
    if (not additions or not added_cues <= set(held)
            or decision['holds'] != [h for h in parent['holds'] if h['cue_id'] not in added_cues]
            or set(ext['cue_ids']) != added_cues):
        raise ValueError('Only explicitly reviewed original holds may be filled')
    if any(held[cue]['reason'] != 'Source multi-role/unknown requires explicit production casting'
           for cue in added_cues):
        raise ValueError('Only casting holds may be filled; preserve source and timing blockers')
    mapping = reused_voices(Path(ext['voice_manifest_path']), project,
                            {u['role'] for u in additions}, inputs)
    evidence = pinned(ext['cue_evidence_path'], ext['cue_evidence_sha256'])
    inputs[ext['cue_evidence_path']] = ext['cue_evidence_sha256']
    reviewed = {r['cue_id']: r for r in evidence['unknown_27']}
    for u in additions:
        r = reviewed[u['cue_id']]
        if (r['episode'] != episode or r['production_role_candidate'] != u['role']
                or r['translation_unchanged'] != u['translation']
                or u['original_script_role'] != 'unknown'
                or u['source_speaker_audio_verified'] is not False):
            raise ValueError('Added casting differs from reviewed source cue')
    new = []
    for i, u in enumerate(additions, 1):
        request = {'projectId': project, 'model': 'speech-2.8-hd', 'text': u['translation'],
                   'voiceId': mapping[u['role']]['voice_id'], 'languageBoost': 'Portuguese',
                   'format': 'wav', 'speed': 1.0, 'vol': 1.0, 'pitch': 0,
                   'emotion': u['emotion'], 'duration': None, 'language': None,
                   'outputFormat': None, 'prompt': None, 'referenceVideoList': []}
        new.append({'id': f'p{project}-e{episode:02d}-added-{i:03d}', 'role': u['role'],
                    'delivery_mode': u['delivery_mode'], 'cue_ids': [u['cue_id']],
                    'unit_ids': [u['id']], 'text': u['translation'], 'start': u['start'],
                    'end': u['end'], 'request': request, 'cache_key': speech.request_key(request)})
    groups = sorted(copy.deepcopy(old['groups']) + new, key=lambda g: g['start'])
    preserved_groups(old['groups'], groups)
    if any(left['end'] > right['start'] + .001 for left, right in zip(groups, groups[1:])):
        raise ValueError('Added speech overlaps an existing group window')
    voices_by_role = {}
    for g in groups:
        voice = g['request']['voiceId']
        if g['role'] in voices_by_role and voices_by_role[g['role']] != voice:
            raise ValueError('One stable voice required per production role')
        voices_by_role[g['role']] = voice
    if len(set(voices_by_role.values())) != len(voices_by_role):
        raise ValueError('Different characters in one episode require distinct voices')
    plan = copy.deepcopy(old)
    plan.update(groups=groups, holds=decision['holds'], inputs_sha256=inputs,
                max_new_tts=len({g['cache_key'] for g in groups}),
                casting_extension={'added_ids': [g['id'] for g in new],
                                   'new_request_limit': len({g['cache_key'] for g in new}),
                                   'preserved_paid_groups': len(old['groups'])})
    return plan


def generate(plan, decision_path, config):
    root = pipeline.audio_root(decision_path)
    delta_root = root/'added-speech'; delta_root.mkdir(exist_ok=True)
    added = set(plan['casting_extension']['added_ids'])
    delta = {**plan, 'groups': [g for g in plan['groups'] if g['id'] in added],
             'max_new_tts': plan['casting_extension']['new_request_limit']}
    path = delta_root/'speech-plan.private.json'
    if path.exists() and read_json(path) != delta:
        raise ValueError('Previously reserved additions changed')
    if not path.exists(): save_json(path, delta)
    check = root/'candidate-plan-check.private.json'
    approval = {'plan_sha256': digest(path), 'max_new_tts': delta['max_new_tts'],
                'new_clones': 0, 'speech_groups_approved': True,
                'audit_report_path': str(check), 'audit_report_sha256': digest(check)}
    target = delta_root/'speech-approval.private.json'
    if target.exists() and read_json(target) != approval:
        raise ValueError('Frozen additions approval changed')
    if not target.exists(): save_json(target, approval)
    speech.ROOT = delta_root
    def current_delta():
        actual = build(decision_path)
        return {**actual, 'groups': [g for g in actual['groups'] if g['id'] in added],
                'max_new_tts': actual['casting_extension']['new_request_limit']}
    speech.generate(delta, config, expected_scope=(100, plan['episode']),
                    current_plan_builder=current_delta, max_groups=32)
    rows = []
    for g in plan['groups']:
        folder = speech.CACHE/g['cache_key']
        req, task, receipt = speech.read_cache(folder, g['cache_key'], g['request'])
        if receipt is None: raise ValueError('No complete paid audio for combined episode')
        rows.append({'group_id': g['id'], 'key': g['cache_key'], 'task_id': task,
                     'raw_path': str(speech.recovery_folder(folder, g['cache_key'], g['request'])/'raw.wav'),
                     'raw_sha256': receipt['sha256'], 'request_fingerprint': fingerprint(req),
                     'seconds': receipt['wave']['seconds'], 'reused_completed_audio': g['id'] not in added})
    result = {'plan_sha256': digest(root/'speech-plan.private.json'), 'groups': rows,
              'new_clone_count': 0, 'native_listening_passed': False,
              'new_submission_attempts': read_json(delta_root/'generation-result.private.json')['new_submission_attempts']}
    path = root/'generation-result.private.json'
    if path.exists() and read_json(path) != result: raise ValueError('Completed combined result changed')
    if not path.exists(): save_json(path, result)
    save_json(root/'progress.private.json', {'stage': 'grouped_speech_ready_fit_pending',
              'completed': len(rows), 'total': len(rows), 'new_clones': 0,
              'added_request_limit': delta['max_new_tts']})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--decision', type=Path, required=True)
    p.add_argument('--stage', choices=('prepare', 'plan_check', 'generate', 'fit'), required=True)
    p.add_argument('--config', type=Path); p.add_argument('--ffmpeg', type=Path)
    args = p.parse_args()
    if sys.platform != 'win32': raise ValueError('Windows business execution only')
    plan = build(args.decision); root = pipeline.audio_root(args.decision)
    root.mkdir(exist_ok=True); speech.CACHE = Path('output/review-project-100/paid-speech-cache')
    with process_lock(root/'production.lock', timeout=0):
        path = root/'speech-plan.private.json'
        if path.exists() and read_json(path) != plan: raise ValueError('Frozen extension changed')
        if not path.exists(): save_json(path, plan)
        subtitle = root/'pt-BR-production-candidate.srt'
        if subtitle.exists() and subtitle.read_text(encoding='utf-8') != plan['subtitle_text']:
            raise ValueError('Frozen subtitles changed')
        if not subtitle.exists(): subtitle.write_text(plan['subtitle_text'], encoding='utf-8')
        if args.stage == 'plan_check':
            check = {'plan_sha256': digest(path), 'preserved_paid_groups': plan['casting_extension']['preserved_paid_groups'],
                     'new_request_limit': plan['casting_extension']['new_request_limit'], 'new_clones': 0,
                     'native_listening_passed': False, 'old_paid_audio_verified': True}
            if not 1 <= check['new_request_limit'] <= 24: raise ValueError('Added request bound exceeded')
            for name, body in [('candidate-plan-check.private.json', check),
                               ('speech-approval.private.json', {'plan_sha256': digest(path), **check})]:
                out = root/name
                if out.exists() and read_json(out) != body: raise ValueError('Frozen extension audit changed')
                if not out.exists(): save_json(out, body)
        elif args.stage == 'generate':
            if not args.config: raise ValueError('Private config required')
            check = read_json(root/'speech-approval.private.json')
            if check['plan_sha256'] != digest(path): raise ValueError('Extension approval changed')
            with process_lock(Path('output/paid-production.lock'), timeout=0):
                generate(plan, args.decision, args.config)
        elif args.stage == 'fit':
            if not args.ffmpeg: raise ValueError('FFmpeg required')
            if plan['holds']: raise ValueError('Remaining source holds prevent rendering')
            fitting.ROOT = root
            if not (root/'render-report.private.json').exists():
                media = (Path(plan['media']['video']), Path(plan['media']['background']))
                fit = fitting.fitted(plan, args.ffmpeg, media)
                if not fit['blocked']:
                    fitting.render(plan, fit, args.ffmpeg, media, f'project100_EP{plan["episode"]:02d}_pt-BR.mp4')
    print('CASTING_EXTENSION_STAGE', plan['episode'], args.stage)


if __name__ == '__main__': main()
