"""Apply an explicit candidate-only reference policy; not speaker identity or native listening."""
import argparse
import difflib
import re
import time
import wave
from pathlib import Path
import sys
import numpy as np
from dub_episode import digest
from translate import read_json,save_json
from process_lock import process_lock


def words(text):
    return re.findall(r'[a-z0-9]+',text.lower().replace('’',"'"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows reference candidate checks only')
    plan=read_json(args.plan);policy=read_json(args.policy);project,role=plan['project_id'],plan['role']
    if (policy.get('approve_reference_candidates') is not True or role not in policy['reference_roles'].get(str(project),[])
        or policy.get('native_listening_approved') is not False or policy.get('max_clones_per_role')!=1):
        raise ValueError('Explicit project/role candidate reference policy required')
    root=Path(f'output/review-project-{project}/pipeline-voices-20261031')/role
    with process_lock(root/'reference.lock',timeout=0):
        receipt=read_json(root/'reference-receipt.private.json');asr=read_json(root/'reference-asr.private.json')
        wav=root/'reference.wav'
        if (receipt['plan_sha256']!=digest(args.plan) or digest(wav)!=receipt['sha256']
            or asr['reference_sha256']!=receipt['sha256'] or any(digest(p)!=h for p,h in plan['inputs_sha256'].items())):
            raise ValueError('Actual reference/source binding differs')
        target=root/'clone-approval.private.json'
        if target.exists():
            old=read_json(target)
            if old['reference_sha256']!=receipt['sha256']:raise ValueError('Existing voice approval changed')
            print('EXISTING_REFERENCE_APPROVAL_PRESERVED',project,role);return
        model=Path('output/tools/source-asr-models/large-v3')
        official=read_json(model/'official-source.json')
        expected_model=next(x['lfs']['sha256'] for x in official['siblings'] if x['rfilename']=='model.bin')
        if asr.get('model_sha256')!=expected_model or digest(model/'model.bin')!=expected_model:
            raise ValueError('Reference screening model binding differs')
        expected=words(' '.join(s['source_text'] for s in plan['segments']));actual=words(' '.join(s['text'] for s in asr['segments']))
        ratio=difflib.SequenceMatcher(None,expected,actual,autojunk=False).ratio()
        with wave.open(str(wav),'rb') as reader:
            if reader.getsampwidth()!=2 or reader.getnchannels()!=1:raise ValueError('Prepared reference format differs')
            samples=np.frombuffer(reader.readframes(reader.getnframes()),dtype='<i2').astype('float64')/32768
        rms=float(np.sqrt(np.mean(samples*samples)));clipped=float(np.mean(np.abs(samples)>=.999))
        issues=[]
        if ratio<policy['minimum_reference_word_match']:issues.append('Reference content requires individual review')
        if rms<.003 or clipped>.002:issues.append('Reference level/clipping requires individual review')
        minimum=10 if plan['platform']=='minimax' else 3
        if not minimum<=receipt['seconds']<=45:issues.append('Reference duration outside candidate bounds')
        audit={'mode':'automated_reference_candidate_checks','project_id':project,'role':role,
               'plan_sha256':digest(args.plan),'policy_sha256':digest(args.policy),'reference_sha256':receipt['sha256'],
               'reference_receipt_sha256':digest(root/'reference-receipt.private.json'),'asr_sha256':digest(root/'reference-asr.private.json'),
               'word_match_ratio':ratio,'rms':rms,'clipped_fraction':clipped,'issues':issues,
               'source_speaker_audio_verified':False,'native_listening_passed':False,'track_purity_verified':False}
        audit_path=root/'reference-candidate-check.private.json'
        if audit_path.exists() and read_json(audit_path)!=audit:raise ValueError('Prior reference evidence changed')
        if not audit_path.exists():save_json(audit_path,audit)
        if issues:
            print('REFERENCE_INDIVIDUAL_REVIEW_REQUIRED',project,role);return
        bank=root.parent/'voice-bank.private.json'
        if bank.exists() and role in read_json(bank)['voices']:
            print('EXISTING_VOICE_REUSE_REQUIRED',project,role);return
        if project==100 and role in read_json('output/review-project-100/voice-bank-minimax-20261031/voice-bank.private.json')['voices']:
            raise ValueError('Original voice already exists; never clone it again')
        from mflix_client import Mflix
        client=Mflix(args.config);remote={}
        for kind in ('character','other'):
            remote[kind]=client.call('getProjectRoles',{'projectId':project,'type':kind,'roleIds':[],'isNeedAsset':False})
        def remote_voices(value):
            if isinstance(value,dict):return [v for k,v in value.items() if k in ('voiceId','voice_id','voices') and v]+[x for v in value.values() for x in remote_voices(v)]
            if isinstance(value,list):return [x for v in value for x in remote_voices(v)]
            return []
        if remote_voices(remote):raise ValueError('Remote voice fields need reuse reconciliation')
        local=[]
        for path in Path(f'output/review-project-{project}').rglob('*voice*bank*.json'):
            saved=read_json(path);local.append({'path':str(path),'sha256':digest(path),'roles':list(saved.get('voices',{}))})
            if role in saved.get('voices',{}):raise ValueError('Reusable role found before approval')
        search=root/'existing-voice-search.private.json'
        if not search.exists():save_json(search,{'project_id':project,'roles_with_no_reusable_voice_identified':[role],
            'catalog_coverage':'partial_no_voice_listing_tool','remote_project_roles':remote,'local_banks':local,'checked_at':time.time()})
        approval={'project_id':project,'role':role,'platform':plan['platform'],'plan_sha256':receipt['plan_sha256'],
                  'reference_sha256':receipt['sha256'],'reference_receipt_sha256':digest(root/'reference-receipt.private.json'),
                  'clone_reference_candidates_approved':True,'max_new_clones':1,'native_listening_passed':False,
                  'source_speaker_audio_verified':False,'approval_mode':'explicit_technical_candidate_policy_not_identity_or_native_listening',
                  'audit_report_path':str(audit_path),'audit_report_sha256':digest(audit_path),
                  'existing_voice_search_path':str(search),'existing_voice_search_sha256':digest(search)}
        save_json(target,approval)
        print('REFERENCE_CANDIDATE_POLICY_APPROVED',project,role)


if __name__=='__main__':main()
