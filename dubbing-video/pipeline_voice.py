"""Prepare or create one explicitly reviewed reusable role voice, never dialogue TTS."""
import argparse
import re
from pathlib import Path
import sys

from dub_episode import digest, probe, run, safe_submit
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
from pipeline_publish import upload, object_key


def voice_result(result,project,role,platform):
    if (not isinstance(result,dict) or 'taskId' in result or 'taskStatus' in result
        or result.get('error') or not isinstance(result.get('voiceId'),str)
        or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}',result['voiceId'])
        or ('projectId' in result and str(result['projectId'])!=str(project))
        or ('platform' in result and result['platform'].lower()!=platform)):
        raise ValueError('Unknown clone outcome; never resubmit')
    if platform=='cartesia' and not result['voiceId'].startswith('cartesia:'):
        raise ValueError('Expected Cartesia voice namespace')
    return result['voiceId']


def prepare(plan_path,ffmpeg):
    plan=read_json(plan_path);project=plan['project_id'];role=plan['role'];platform=plan['platform']
    if project not in (96,100,102,110) or platform not in ('minimax','cartesia') or not re.fullmatch(r'[a-z][a-z0-9_]{0,60}',role):
        raise ValueError('Invalid reference scope')
    root=Path(f'output/review-project-{project}/pipeline-voices-20261031')/role
    root.mkdir(parents=True,exist_ok=True)
    with process_lock(root/'reference.lock',timeout=0):
        for path,sha in plan['inputs_sha256'].items():
            if digest(path)!=sha:raise ValueError('Reference source changed')
        marker=root/'plan-binding.private.json';binding={'plan_sha256':digest(plan_path),'plan':plan}
        if marker.exists() and read_json(marker)!=binding:raise ValueError('Role reference inputs changed; preserve original voice')
        save_json(marker,binding)
        target=root/'reference.wav';receipt=root/'reference-receipt.private.json'
        if not receipt.exists() and (root/'clone.private.json').exists():
            raise ValueError('Clone exists without its original reference receipt')
        if receipt.exists():
            old=read_json(receipt)
            if old['plan_sha256']!=digest(plan_path) or digest(target)!=old['sha256']:
                raise ValueError('Reference cache changed')
            return root,plan,old
        parts=[];intervals={}
        for i,seg in enumerate(plan['segments']):
            path=Path(seg['path']);start,end=seg['start'],seg['end']
            if (digest(path)!=seg['sha256'] or not 0<=start<end<=float(probe(path,ffmpeg)['format']['duration'])+.001
                or any(start<b and a<end for a,b in intervals.setdefault(str(path),[]))):
                raise ValueError('Reference source/time/overlapping duplicate differs')
            intervals[str(path)].append((start,end))
            part=root/f'part-{i:02d}.wav'
            run([ffmpeg,'-nostdin','-v','error','-y','-ss',str(start),'-i',path,'-t',str(end-start),
                 '-ar','44100','-ac','1','-c:a','pcm_s16le',part]);parts.append(part)
        if not parts:raise ValueError('Actual source segments required')
        command=[ffmpeg,'-nostdin','-v','error','-y']
        for part in parts:command+=['-i',str(part)]
        graph=''.join(f'[{i}:a]' for i in range(len(parts)))+f'concat=n={len(parts)}:v=0:a=1[out]'
        run(command+['-filter_complex',graph,'-map','[out]','-c:a','pcm_s16le',target])
        seconds=float(probe(target,ffmpeg)['format']['duration'])
        minimum=10 if platform=='minimax' else 3
        if not minimum<=seconds<=45 or target.stat().st_size>16*1024*1024:
            raise ValueError('Reference outside production bounds; never pad or duplicate speech')
        value={'plan_sha256':digest(plan_path),'sha256':digest(target),'seconds':seconds,
               'source_speaker_audio_verified':False,'native_listening_passed':False}
        save_json(receipt,value)
        return root,plan,value


def clone(root,plan,reference,approval_path,config):
    project,role,platform=plan['project_id'],plan['role'],plan['platform']
    bank_path=root.parent/'voice-bank.private.json'
    with process_lock(Path('output/paid-production.lock'),timeout=0),process_lock(root.parent/'bank.lock',timeout=0),process_lock(root/'reference.lock',timeout=0):
        binding=read_json(root/'plan-binding.private.json')
        if (binding['plan']!=plan or binding['plan_sha256']!=reference['plan_sha256']
            or read_json(root/'reference-receipt.private.json')!=reference
            or digest(root/'reference.wav')!=reference['sha256']
            or any(digest(path)!=sha for path,sha in plan['inputs_sha256'].items())):
            raise ValueError('Actual reference or source changed after preparation; no clone submitted')
        approval=read_json(approval_path)
        if (approval['project_id']!=project or approval['role']!=role or approval['platform']!=platform
            or approval['plan_sha256']!=reference['plan_sha256']
            or approval['reference_sha256']!=reference['sha256'] or approval['reference_receipt_sha256']!=digest(root/'reference-receipt.private.json')
            or approval['clone_reference_candidates_approved'] is not True or approval['max_new_clones']!=1
            or digest(approval['audit_report_path'])!=approval['audit_report_sha256']
            or digest(approval['existing_voice_search_path'])!=approval['existing_voice_search_sha256']):
            raise ValueError('Actual reviewed reference/search approval changed')
        search=read_json(approval['existing_voice_search_path'])
        if search['project_id']!=project or role not in search['roles_with_no_reusable_voice_identified']:
            raise ValueError('Reusable voice search does not support creating this role')
        bank=read_json(bank_path) if bank_path.exists() else {'project_id':project,'voices':{}}
        if bank['project_id']!=project:raise ValueError('Voice bank scope changed')
        receipt=root/'clone.private.json';marker=root/'clone-input.private.json'
        basis={'project_id':project,'role':role,'platform':platform,'reference_sha256':reference['sha256'],
               'reference_receipt_sha256':digest(root/'reference-receipt.private.json'),'approval_sha256':digest(approval_path),'approval_path':str(approval_path)}
        if marker.exists() and read_json(marker)!=basis:raise ValueError('Immutable clone input changed')
        if not marker.exists() and (receipt.exists() or (root/'clone.private.submission-pending.json').exists()):
            raise ValueError('Orphan clone evidence')
        save_json(marker,basis)
        if receipt.exists():
            payload=read_json(root/'clone-request.private.json')
            if (payload['request']['projectId']!=project or payload['request']['platform']!=platform
                or payload['request']['name']!=f'project{project}_{role}'
                or read_json(root/'request-fingerprint.private.json')['fingerprint']!=fingerprint(payload)):
                raise ValueError('Clone receipt lost its immutable payload')
        if role in bank['voices']:
            item=bank['voices'][role]
            if (not receipt.exists() or item['voice_id']!=voice_result(read_json(receipt),project,role,platform)
                or item['clone_receipt_sha256']!=digest(receipt) or item['basis']!=basis
                or item['request_sha256']!=digest(root/'clone-request.private.json')):raise ValueError('Voice bank changed')
            return item
        if project==100:
            old=read_json('output/review-project-100/voice-bank-minimax-20261031/voice-bank.private.json')
            if role in old['voices']:raise ValueError('Existing original role voice must be reused, never cloned again')
        if not receipt.exists():
            if (root/'clone.private.submission-pending.json').exists():raise ValueError('Unknown clone already submitted')
            from mflix_client import Mflix
            client=Mflix(config)
            upload_path=root/'upload-ledger.private.json'
            ledger=read_json(upload_path) if upload_path.exists() else {'uploads':{},'items':{}}
            manifest=read_json('output/four-dramas-20261030/intake-manifest.private.json')
            protected={object_key(x['url']) for x in manifest['items'] if isinstance(x.get('url'),str)}
            url=upload(client,root/'reference.wav',ledger,upload_path,protected)
            request={'request':{'projectId':project,'name':f'project{project}_{role}','platform':platform,
                'referenceAudioUrl':url,'remark':'Reusable production role voice; source attribution candidate, native pt-BR listening pending.'}}
            request_path=root/'clone-request.private.json'
            if request_path.exists() and read_json(request_path)!=request:raise ValueError('Clone request changed')
            save_json(request_path,request)
            fp_path=root/'request-fingerprint.private.json'
            if fp_path.exists() and read_json(fp_path)['fingerprint']!=fingerprint(request):raise ValueError('Clone payload fingerprint changed')
            save_json(fp_path,{'fingerprint':fingerprint(request)})
            result=safe_submit(client,'uploadVoice',request,receipt)
        else:result=read_json(receipt)
        item={'voice_id':voice_result(result,project,role,platform),'platform':platform,'role':role,'basis':basis,
              'clone_receipt_sha256':digest(receipt),'request_sha256':digest(root/'clone-request.private.json'),'source_speaker_audio_verified':False,'native_listening_passed':False}
        if any(v['voice_id']==item['voice_id'] for v in bank['voices'].values()):raise ValueError('Duplicate voice ID across roles')
        bank['voices'][role]=item;save_json(bank_path,bank)
        return item


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--ffmpeg',type=Path,required=True)
    parser.add_argument('--approval',type=Path);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows voice preparation/production only')
    root,plan,reference=prepare(args.plan,args.ffmpeg)
    if args.approval:
        if not args.config:raise ValueError('Private config required for clone')
        result=clone(root,plan,reference,args.approval,args.config)
        print('REUSABLE_ROLE_VOICE_READY',plan['project_id'],plan['role'],result['platform'])
    else:print('REFERENCE_CANDIDATE_READY',plan['project_id'],plan['role'],reference['seconds'])


if __name__=='__main__':main()
