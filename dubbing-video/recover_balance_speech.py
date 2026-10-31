"""One explicitly permitted replacement of a confirmed terminal balance failure."""
import argparse
from pathlib import Path
import sys,time
from urllib.parse import urlsplit
from dub_episode import digest,safe_submit
from translate import read_json,save_json,fingerprint
from process_lock import process_lock
import generate_monte_episode01 as speech


def validate_permit(permit,folder,key,request):
    old=read_json(folder/'submission.private.json');status=read_json(folder/'task.private.json')['result']
    if (permit.get('project_id')!=request['projectId'] or permit.get('key')!=key
        or permit.get('original_task_id')!=old['taskId'] or permit.get('max_new_submissions')!=1
        or permit.get('approved_once') is not True or request.get('model')!='speech-2.8-hd'
        or status['taskStatus']!=3 or 'insufficient balance' not in str(status.get('taskMessage','')).lower()
        or any((folder/n).exists() for n in ('raw.wav','raw-receipt.private.json','raw-receipt.prepared.private.json','submission.private.submission-pending.json'))):
        raise ValueError('Only explicit terminal MiniMax balance failures without audio may be replaced')
    required={'request.private.json','submission.private.json','task.private.json'}
    if set(permit['original_sha256'])!=required or any(digest(folder/n)!=h for n,h in permit['original_sha256'].items()):
        raise ValueError('Original failed receipt changed')
    plan_path=Path(permit['plan_path']);plan=read_json(plan_path)
    if digest(plan_path)!=permit['plan_sha256'] or not any(g['cache_key']==key and g['request']==request for g in plan['groups']):
        raise ValueError('Request differs from actual frozen source plan')
    if any(digest(p)!=h for p,h in plan['inputs_sha256'].items()):raise ValueError('Original source inputs changed')
    if digest(permit['audit_report_path'])!=permit['audit_report_sha256']:raise ValueError('Recovery audit changed')
    pause=Path('output/paid-production-paused.private.json')
    if pause.exists() and (permit.get('allow_one_balance_probe_while_paused') is not True or digest(pause)!=permit['paused_file_sha256']):
        raise ValueError('Explicit probe permit must bind the current paid pause')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--permit',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    args=p.parse_args()
    if sys.platform!='win32':raise ValueError('Windows paid recovery only')
    permit=read_json(args.permit);project=permit['project_id'];key=permit['key']
    if project!=100 or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Invalid Count request scope')
    base=Path(f'output/review-project-{project}');old=base/'paid-speech-cache'/key;target=base/'paid-speech-balance-recovery-01'/key
    with process_lock(Path('output/paid-production.lock'),timeout=0),process_lock(old/'cache.lock',timeout=0):
        request=read_json(old/'request.private.json')['request'];validate_permit(permit,old,key,request)
        if speech.request_key(request)!=key:raise ValueError('Exact request key differs')
        target.mkdir(parents=True,exist_ok=True);binding=target/'recovery-binding.private.json';value={'permit_path':str(args.permit),'permit_sha256':digest(args.permit)}
        if binding.exists() and read_json(binding)!=value:raise ValueError('Earlier recovery permit differs')
        if not binding.exists():save_json(binding,value)
        from mflix_client import Mflix
        client=Mflix(args.config)
        original=speech.validate_status(client.task(permit['original_task_id']),permit['original_task_id'])
        if original['taskStatus']!=3 or 'insufficient balance' not in str(original.get('taskMessage','')).lower() or original.get('resultAudioUrl') or original.get('resultAudioUrls'):
            raise ValueError('Fresh old task is not an empty terminal balance failure')
        fresh=target/'original-recheck.private.json'
        if not fresh.exists():save_json(fresh,{'result':original,'checked_at':time.time()})
        marker=target/'request.private.json';body={'key':key,'request':request}
        if marker.exists() and read_json(marker)!=body:raise ValueError('Recovery request differs')
        if not marker.exists():save_json(marker,body)
        reservation=target/'attempt-reservation.private.json'
        if not reservation.exists():save_json(reservation,{'original_task_id':permit['original_task_id'],'max_new_submissions':1,'request_fingerprint':fingerprint(request),'reserved_at':time.time()})
        submitted=target/'submission.private.json'
        task=speech.accepted_task(read_json(submitted) if submitted.exists() else safe_submit(client,'generateAudio',{'request':request},submitted))
        cached_ready=speech._read_cache_origin(target,key,request)[2] is not None
        status=read_json(target/'task.private.json')['result'] if (target/'task.private.json').exists() else None
        deadline=time.monotonic()+900
        while not cached_ready:
            status=speech.validate_status(client.task(task),task);save_json(target/'task.private.json',{'task_id':task,'result':status})
            if status['taskStatus'] in (2,3):break
            if time.monotonic()>deadline:raise ValueError('Known recovery pending; poll same task, never resubmit')
            time.sleep(5)
        if status['taskStatus']!=2:raise ValueError('Recovery failed; preserve attempt and do not retry automatically')
        raw=target/'raw.wav';receipt=target/'raw-receipt.private.json'
        if not receipt.exists():
            url=status.get('resultAudioUrl') or (status.get('resultAudioUrls') or [None])[0]
            u=urlsplit(url) if isinstance(url,str) else None
            if u is None or u.scheme!='https' or not u.hostname or u.username or u.password:raise ValueError('Invalid generated URL')
            part=target/'raw.download.part'
            if part.exists():part.rename(target/f'raw.previous-{time.time_ns()}.part')
            size=0
            try:
                with client.http.get(url,stream=True,timeout=120,allow_redirects=False,headers={'Accept-Encoding':'identity'}) as response:
                    response.raise_for_status()
                    if response.status_code!=200 or response.headers.get('Content-Encoding','identity') not in ('identity',''):raise ValueError('Unexpected download')
                    expected=response.headers.get('Content-Length');expected=int(expected) if expected else None
                    with part.open('wb') as out:
                        for chunk in response.iter_content(1024*1024):
                            size+=len(chunk)
                            if size>32*1024*1024:raise ValueError('Audio exceeds limit')
                            out.write(chunk)
                    if not size or expected is not None and size!=expected:raise ValueError('Audio length mismatch')
            except Exception:raise RuntimeError('Known recovery download failed; URL omitted') from None
            r={'key':key,'task_id':task,'request_fingerprint':fingerprint(request),'status_sha256':digest(target/'task.private.json'),'bytes':size,'sha256':digest(part),'wave':speech.wave_evidence(part)}
            save_json(target/'raw-receipt.prepared.private.json',r);part.replace(raw);(target/'raw-receipt.prepared.private.json').replace(receipt)
        speech._read_cache_origin(target,key,request)
        link=old/'balance-recovery-link.private.json';value={'key':key,'target':str(target),'original_task_id':permit['original_task_id'],'original_sha256':permit['original_sha256'],'permit_path':str(args.permit),'permit_sha256':digest(args.permit),'recovery_task_id':task,'recovery_receipt_sha256':digest(receipt)}
        if link.exists() and read_json(link)!=value:raise ValueError('Existing completed recovery differs')
        if not link.exists():save_json(link,value)
        speech.read_cache(old,key,request)
        print('BALANCE_RECOVERY_AUDIO_READY',project,permit['original_task_id'],task,read_json(receipt)['wave']['seconds'])

if __name__=='__main__':main()
