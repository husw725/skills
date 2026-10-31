"""Approve only frozen candidate speech requests under an explicit project production policy."""
import argparse
from pathlib import Path
import sys
from dub_episode import digest
from pipeline_speech import build
from translate import read_json,save_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision',type=Path,required=True);parser.add_argument('--policy',type=Path,required=True)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows production policy checks only')
    policy=read_json(args.policy);decision=read_json(args.decision)
    if (policy.get('approve_frozen_candidate_speech') is not True or decision['project_id'] not in policy['projects']
        or policy.get('native_listening_approved') is not False or policy.get('allow_paid_regeneration') is not False):
        raise ValueError('Explicit bounded candidate production policy required')
    root=args.decision.parent/'pipeline-audio-20261031-v1';path=root/'speech-plan.private.json';plan=read_json(path)
    if build(args.decision)!=plan or plan['max_new_tts']!=len({g['cache_key'] for g in plan['groups']}):
        raise ValueError('Actual frozen plan changed')
    if not 1<=plan['max_new_tts']<=policy['max_unique_requests_per_episode']:
        raise ValueError('Candidate speech exceeds project request bound')
    audit={'mode':'automated_frozen_candidate_plan_checks','plan_sha256':digest(path),'policy_sha256':digest(args.policy),
           'project_id':plan['project_id'],'episode':plan['episode'],'groups':len(plan['groups']),
           'unique_requests':plan['max_new_tts'],'no_new_clones':True,'source_holds':plan['holds'],
           'text_and_casting_basis':'source-bound reviewed translation and explicit production casting candidates',
           'original_actor_identity_verified':False,'native_listening_passed':False,'acting_verified':False}
    report=root/'candidate-plan-check.private.json'
    if report.exists() and read_json(report)!=audit:raise ValueError('Existing plan audit differs')
    if not report.exists():save_json(report,audit)
    approval={'plan_sha256':digest(path),'max_new_tts':plan['max_new_tts'],'new_clones':0,'speech_groups_approved':True,
              'approval_scope':'frozen production candidate requests, not actor identity or native listening',
              'native_listening_passed':False,'audit_report_path':str(report),'audit_report_sha256':digest(report)}
    target=root/'speech-approval.private.json'
    if target.exists() and read_json(target)!=approval:raise ValueError('Existing speech approval differs')
    if not target.exists():save_json(target,approval)
    print('FROZEN_CANDIDATE_SPEECH_APPROVED',plan['project_id'],plan['episode'],plan['max_new_tts'])


if __name__=='__main__':main()
