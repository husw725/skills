"""One exact reviewed text repair; all other paid requests and audio remain unchanged."""
import argparse
from pathlib import Path
import sys

from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json
import pipeline_speech as pipeline
import pipeline_casting_extension as incremental
from repair_cached_alignment import checked_parent, store


def checked(permit_path):
    permit = read_json(permit_path)
    if (permit['project_id'] != 100 or permit['episode'] != 16 or permit['max_new_requests'] != 1
            or permit['new_clones'] != 0 or permit['group_id'] != 'p100-e16-g011'):
        raise ValueError('Only the reviewed one-group Count16 repair is authorized')
    required = {permit['text_review_path'], permit['decision_path'], permit['parent_decision_path']}
    if not required <= set(permit['inputs_sha256']):
        raise ValueError('Freeze review and both production decisions must be hash-bound')
    for path, sha in permit['inputs_sha256'].items():
        if digest(path) != sha: raise ValueError('Reviewed minimal edit inputs changed')
    parent_root, old, _ = checked_parent(permit)
    if pipeline.build(Path(permit['parent_decision_path'])) != old:
        raise ValueError('Original production decision changed')
    decision = Path(permit['decision_path'])
    plan = pipeline.build(decision)
    review = read_json(permit['text_review_path'])['freeze_proposal']
    if (plan['project_id'] != 100 or plan['episode'] != 16 or plan['holds']
            or [g['id'] for g in old['groups']] != [g['id'] for g in plan['groups']]
            or old['media'] != plan['media']):
        raise ValueError('Original picture, cue groups, and coverage must remain intact')
    changed = []
    for before, after in zip(old['groups'], plan['groups']):
        if before == after: continue
        changed.append(after['id'])
        if after['id'] != permit['group_id'] or after['text'] != review['text']:
            raise ValueError('Unreviewed speech group changed')
        for key in set(before) | set(after):
            if key not in ('text', 'request', 'cache_key') and before.get(key) != after.get(key):
                raise ValueError('Minimal text edit changed role, acting, or placement')
        if {k:v for k,v in before['request'].items() if k != 'text'} != {k:v for k,v in after['request'].items() if k != 'text'}:
            raise ValueError('Saved voice or synthesis parameters changed')
        if after['cache_key'] != permit['new_request_key']: raise ValueError('Exact new request fingerprint differs')
    if changed != [permit['group_id']]: raise ValueError('Exactly one reviewed group must change')
    if len(old['production_cues']) != len(plan['production_cues']): raise ValueError('Cue count changed')
    changed_cues = []
    for before, after in zip(old['production_cues'], plan['production_cues']):
        if {k:v for k,v in before.items() if k != 'translation'} != {k:v for k,v in after.items() if k != 'translation'}:
            raise ValueError('Original cue identity or time changed')
        expected = review['cue_translations'].get(before['id'], before['translation'])
        if after['translation'] != expected: raise ValueError('Subtitle wording differs from reviewed repair')
        if before != after: changed_cues.append(before['id'])
    if changed_cues != review['change_only_cue_ids']: raise ValueError('Minimal subtitle edit scope changed')
    root = pipeline.audio_root(decision)
    if root.resolve() == parent_root.resolve(): raise ValueError('Keep original paid production version')
    return permit, decision, plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--permit', type=Path, required=True); p.add_argument('--config', type=Path, required=True)
    args = p.parse_args()
    if sys.platform != 'win32': raise ValueError('Windows production only')
    permit, decision, plan = checked(args.permit)
    root = pipeline.audio_root(decision); root.mkdir(exist_ok=True)
    with process_lock(root/'production.lock', timeout=0), process_lock(Path('output/paid-production.lock'), timeout=0):
        store(root/'speech-plan.private.json', plan)
        subtitle = root/'pt-BR-production-candidate.srt'
        if subtitle.exists() and subtitle.read_text(encoding='utf-8') != plan['subtitle_text']:
            raise ValueError('Frozen repaired subtitles changed')
        if not subtitle.exists(): subtitle.write_text(plan['subtitle_text'], encoding='utf-8')
        store(root/'candidate-plan-check.private.json', {'permit_sha256': digest(args.permit),
              'plan_sha256': digest(root/'speech-plan.private.json'), 'max_new_requests': 1,
              'new_clones': 0, 'all_other_paid_audio_reused': True, 'native_listening_passed': False})
        incremental.speech.CACHE = Path('output/review-project-100/paid-speech-cache')
        def current(path): return checked(args.permit)[2]
        incremental.generate(plan, decision, args.config, current_plan_builder=current,
                             increment={'added_ids':[permit['group_id']], 'new_request_limit':1})
    print('REVIEWED_TEXT_INCREMENT_READY', 100, 16, 'MAX_NEW_REQUESTS', 1, 'NEW_CLONES', 0)


if __name__ == '__main__': main()
