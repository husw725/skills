"""Finish first-pass MiniMax groups while preserving an unrelated unresolved Cartesia task."""
import argparse
from pathlib import Path
import sys

from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json
import pipeline_speech as pipeline
import generate_monte_episode01 as speech
from repair_cached_alignment import store


def subset(master,ids):
    rows=[g for g in master['groups'] if g['id'] in ids]
    if (len(rows)!=len(ids) or not 1<=len(rows)<=10
            or any(g['request']['model']!='speech-2.8-hd' for g in rows)):
        raise ValueError('Only bounded original first-pass MiniMax groups may be submitted')
    return {**master,'groups':rows,'max_new_tts':len({g['cache_key'] for g in rows})}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--decision',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    args=p.parse_args()
    if sys.platform!='win32':raise ValueError('Windows business execution only')
    master_root=pipeline.audio_root(args.decision);master_path=master_root/'speech-plan.private.json'
    master=read_json(master_path)
    if (master['project_id'],master['episode'])!=(100,2) or pipeline.build(args.decision)!=master:
        raise ValueError('Exact original approved Count2 production plan required')
    approval=read_json(master_root/'speech-approval.private.json')
    if (approval['plan_sha256']!=digest(master_path) or not approval['speech_groups_approved']
            or approval['new_clones']!=0 or approval['max_new_tts']!=master['max_new_tts']
            or master['max_new_tts']!=len({g['cache_key'] for g in master['groups']})
            or digest(approval['audit_report_path'])!=approval['audit_report_sha256']):
        raise ValueError('Original finite production approval changed')
    root=master_root/'remaining-minimax-20261101';root.mkdir(exist_ok=True)
    speech.CACHE=Path('output/review-project-100/paid-speech-cache');speech.ROOT=root
    with process_lock(master_root/'production.lock',timeout=0),process_lock(Path('output/paid-production.lock'),timeout=0):
        permit_path=root/'first-pass-scope.private.json'
        if permit_path.exists():
            permit=read_json(permit_path)
            if permit['master_plan_sha256']!=digest(master_path):raise ValueError('Frozen first-pass scope changed')
            ids=permit['group_ids']
        else:
            ids=[]
            for g in master['groups']:
                if g['request']['model']!='speech-2.8-hd':continue
                _,task,receipt=speech.read_cache(speech.CACHE/g['cache_key'],g['cache_key'],g['request'])
                if receipt is None:
                    if task is not None:raise ValueError('Known paid MiniMax work must be reconciled before a new subset')
                    ids.append(g['id'])
            subset(master,ids)
            save_json(permit_path,{'master_plan_sha256':digest(master_path),'group_ids':ids,
                                  'new_first_pass_request_limit':len(ids),'new_clones':0,
                                  'cartesia_task_not_resubmitted_or_changed':42727})
        def build():
            current=pipeline.build(args.decision)
            if current!=master or digest(master_path)!=read_json(permit_path)['master_plan_sha256']:
                raise ValueError('Original production plan changed')
            return subset(current,ids)
        plan=build();store(root/'speech-plan.private.json',plan)
        check={'master_plan_sha256':digest(master_path),'scope_sha256':digest(permit_path),
               'max_first_pass_requests':len(ids),'new_clones':0,'all_requests_identical_to_master':True}
        store(root/'candidate-plan-check.private.json',check)
        store(root/'speech-approval.private.json',{'plan_sha256':digest(root/'speech-plan.private.json'),
              'max_new_tts':plan['max_new_tts'],'new_clones':0,'speech_groups_approved':True,
              'audit_report_path':str(root/'candidate-plan-check.private.json'),
              'audit_report_sha256':digest(root/'candidate-plan-check.private.json')})
        speech.generate(plan,args.config,expected_scope=(100,2),current_plan_builder=build,max_groups=10)
    print('ORIGINAL_MINIMAX_SUBSET_READY',len(ids),'CARTESIA_42727_PRESERVED')


if __name__=='__main__':main()
