"""One authorized MiniMax replacement; retain the unresolved Cartesia task and all paid audio."""
import argparse
import copy
from pathlib import Path
import sys

from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json
from repair_cached_alignment import store
import pipeline_speech as pipeline
import pipeline_casting_extension as incremental
import generate_monte_episode01 as speech
import fit_render_monte_episode01 as fitting


GROUP = 'p100-e02-g009'


def replacement_plan(old, request):
    if (old['project_id'], old['episode']) != (100, 2) or old['holds']:
        raise ValueError('Only complete original Count2 cue scope is supported')
    original = [g for g in old['groups'] if g['id'] == GROUP]
    if (len(old['groups']) != 20 or len(original) != 1
            or original[0]['role'] != 'wedding_priest'
            or original[0]['request']['model'] != 'sonic-3.6'):
        raise ValueError('Exact original unresolved priest group required')
    expected = dict(projectId=100, model='speech-2.8-hd', text=original[0]['text'],
                    voiceId='minimax:Portuguese_ReliableMan', languageBoost='Portuguese',
                    format='wav', speed=1.0, vol=1.0, pitch=0, emotion='calm',
                    duration=None, language=None, outputFormat=None, prompt=None,
                    referenceVideoList=[])
    if request != expected:
        raise ValueError('Only the frozen same-text system-voice replacement is supported')
    new = copy.deepcopy(old)
    group = next(g for g in new['groups'] if g['id'] == GROUP)
    group.update(request=copy.deepcopy(request), cache_key=speech.request_key(request))
    new['max_new_tts'] = len({g['cache_key'] for g in new['groups']})
    return new


def checked(permit_path):
    permit = read_json(permit_path)
    if (permit['project_id'], permit['episode'], permit['group_id'],
            permit['original_task_id'], permit['max_additional_requests'], permit['new_clones']) != (100, 2, GROUP, 42727, 1, 0):
        raise ValueError('Exact authorized one-group replacement required')
    if permit.get('user_authorized_minimax_replacement') is not True:
        raise ValueError('Explicit provider replacement authorization missing')
    required = {permit[k] for k in ('parent_decision_path', 'parent_plan_path',
                'decision_path', 'voice_evidence_path', 'audit_report_path',
                'original_request_path', 'original_submission_path')}
    if not required <= set(permit['inputs_sha256']):
        raise ValueError('Freeze the original paid task, both decisions, and reviewed voice evidence')
    for path, sha in permit['inputs_sha256'].items():
        if digest(path) != sha:
            raise ValueError('Frozen source, original paid task, or replacement evidence changed')
    parent_path = Path(permit['parent_plan_path']); old = read_json(parent_path)
    if pipeline.build(Path(permit['parent_decision_path'])) != old:
        raise ValueError('Original production source changed')
    original = next(g for g in old['groups'] if g['id'] == GROUP)
    if (read_json(permit['original_request_path']) != dict(key=original['cache_key'], request=original['request'])
            or speech.accepted_task(read_json(permit['original_submission_path'])) != 42727):
        raise ValueError('Preserve the original accepted Cartesia request')
    voice = read_json(permit['voice_evidence_path'])
    if (voice['studio_voice_id'] != permit['request']['voiceId']
            or voice['system_voice']['voiceId'] != 'Portuguese_ReliableMan'
            or voice['system_voice']['type'] != 'system_voice'
            or voice['brazilian_accent_listening_verified'] is not False):
        raise ValueError('Reviewed system-voice mapping differs')
    for group in old['groups']:
        if group['id'] == GROUP:
            continue
        _, _, receipt = speech.read_cache(speech.CACHE/group['cache_key'], group['cache_key'], group['request'])
        if receipt is None:
            raise ValueError('All other nineteen paid groups must already be complete')
    decision_path = Path(permit['decision_path']); decision = read_json(decision_path)
    expected = copy.deepcopy(read_json(permit['parent_decision_path']))
    expected.update(production_revision=3, provider_replacement_permit_path=str(permit_path))
    if decision != expected:
        raise ValueError('Replacement cannot change original units, words, roles, media, or timing')
    root = pipeline.audio_root(decision_path)
    if root.resolve() == parent_path.parent.resolve():
        raise ValueError('Keep the original paid production directory')
    plan = replacement_plan(old, permit['request'])
    plan['inputs_sha256'].update(permit['inputs_sha256'])
    plan['inputs_sha256'][str(permit_path)] = digest(permit_path)
    plan['provider_replacement'] = dict(group_id=GROUP, original_task_id=42727,
        original_cache_key=original['cache_key'], max_additional_requests=1,
        original_unknown_task_may_still_be_charged=True, system_voice_not_actor_clone=True)
    return decision_path, plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--permit', type=Path, required=True)
    p.add_argument('--stage', choices=('prepare', 'generate', 'fit'), required=True)
    p.add_argument('--config', type=Path); p.add_argument('--ffmpeg', type=Path)
    args = p.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Windows business execution only')
    speech.CACHE = Path('output/review-project-100/paid-speech-cache')
    decision, plan = checked(args.permit); root = pipeline.audio_root(decision)
    root.mkdir(exist_ok=True)
    with process_lock(root/'production.lock', timeout=0):
        store(root/'speech-plan.private.json', plan)
        subtitle = root/'pt-BR-production-candidate.srt'
        if subtitle.exists() and subtitle.read_text(encoding='utf-8') != plan['subtitle_text']:
            raise ValueError('Original production subtitle changed')
        if not subtitle.exists():
            subtitle.write_text(plan['subtitle_text'], encoding='utf-8')
        store(root/'candidate-plan-check.private.json', dict(permit_sha256=digest(args.permit),
            plan_sha256=digest(root/'speech-plan.private.json'), preserved_paid_groups=19,
            max_additional_requests=1, new_clones=0, native_listening_passed=False))
        if args.stage == 'prepare':
            print('PRIEST_REPLACEMENT_PREPARED', len(plan['groups'])); return
        if args.stage == 'generate':
            if not args.config:
                raise ValueError('Private audio config required')
            with process_lock(Path('output/paid-production.lock'), timeout=0):
                incremental.generate(plan, decision, args.config,
                    current_plan_builder=lambda _: checked(args.permit)[1],
                    increment=dict(added_ids=[GROUP], new_request_limit=1))
            print('PRIEST_REPLACEMENT_READY_MAX_ONE_NEW_REQUEST'); return
        if not args.ffmpeg:
            raise ValueError('FFmpeg required')
        fitting.ROOT = root
        media = (Path(plan['media']['video']), Path(plan['media']['background']))
        report = root/'render-report.private.json'
        if report.exists():
            data = read_json(report)
            if data['plan_sha256'] != digest(root/'speech-plan.private.json') or digest(data['output']) != data['output_sha256']:
                raise ValueError('Existing completed media changed')
            return
        fit = fitting.fitted(plan, args.ffmpeg, media)
        if not fit['blocked']:
            fitting.render(plan, fit, args.ffmpeg, media, 'project100_EP02_pt-BR_minimax_priest.mp4')


if __name__ == '__main__':
    main()
