"""First-episode grouped speech: one paid submission per exact cached request."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
from dub_episode import digest, safe_submit
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
import prepare_monte_editorial_queue as editorial
import create_monte_voice_bank as voices

ROOT=Path('output/review-project-100/episode-01/audio-production-20261031-v2')
CACHE=Path('output/review-project-100/paid-speech-cache')


def request_key(request):
    canonical=dict(request)
    for key in ('speed','vol','pitch'):
        value=canonical[key]
        if value is None and key in ('vol','pitch') and request.get('model')=='sonic-3.6':
            continue  # Explicit nullable Cartesia fields remain null.
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('Finite numeric speech parameter required')
        if value==int(value):canonical[key]=int(value)
    return fingerprint(canonical)


def emotion(text):
    text=text.lower()
    rules=[('angry',('ameaç','raiva','furios','indigna','irrit','ressent','autorit','brusc')),
        ('happy',('alegr','feliz','entusiasm','carinh','afetu','amoros','felic')),
        ('sad',('amarga','pesaros','triste','sofr')),
        ('surprised',('surpres','espant','incredul')),
        ('fearful',('medo','receio','ansios','nervos','inquiet'))]
    return next((e for e,words in rules if any(w in text for w in words)),'calm')


def build_plan():
    folder=Path('output/review-project-100/episode-01/editorial-candidate-20261030')
    result=editorial.validate_artifacts(1,folder)
    context=read_json(folder/'source-input.private.json');rows=context['timed_source']
    proposal,ref_fp=voices.approved_inputs()
    bank_path=voices.ROOT/'voice-bank.private.json';bank=read_json(bank_path)
    if (bank['project_id']!=100 or bank['platform']!='minimax' or bank['reference_fingerprint']!=ref_fp
        or set(bank['voices'])!=set(proposal['roles'])):raise ValueError('Complete five-role voice bank required')
    for role in proposal['roles']:voices.check_cached_role(role,voices.source_basis(role,ref_fp),bank)
    override_path=ROOT/'editorial-overrides.private.json'
    overrides=read_json(override_path)
    if not set(overrides).issubset({r['id'] for r in rows}):raise ValueError('Override outside episode scope')
    production_cues=[];groups=[]
    for row,cue in zip(rows,result['candidate']['cues']):
        role=cue['script_role']
        delivery='narration' if 'narra' in cue['emotion_intent'].lower() else 'dialogue'
        text=cue['translation']
        if row['id'] in overrides:
            edit=overrides[row['id']]
            if (edit['source_text']!=row['text'] or edit['baseline_translation']!=text
                or not isinstance(edit['translation'],str) or not edit['translation'].strip()
                or digest(edit['audit_report_path'])!=edit['audit_report_sha256']):
                raise ValueError('Unbound editorial override')
            text=edit['translation']
        production_cues.append({'id':row['id'],'start':row['start'],'end':row['end'],'translation':text})
        if role not in bank['voices']:raise ValueError('Unresolved source role; never substitute another voice')
        if groups and groups[-1]['role']==role and groups[-1]['delivery_mode']==delivery and row['start']-groups[-1]['end']<=1.25:
            group=groups[-1];group['end']=max(group['end'],row['end']);group['cue_ids'].append(row['id'])
            group['text']+=' '+text;group['script_intents'].append(cue['emotion_intent'])
        else:groups.append({'id':f'e01-group-{len(groups)+1:03d}','role':role,'cue_ids':[row['id']],
            'start':row['start'],'end':row['end'],'text':text,'delivery_mode':delivery,
            'script_intents':[cue['emotion_intent']]})
    for group in groups:
        e=emotion(' '.join(group['script_intents']))
        request={'projectId':100,'model':'speech-2.8-hd','text':group['text'],
            'voiceId':bank['voices'][group['role']]['voice_id'],'languageBoost':'Portuguese',
            'format':'wav','speed':1.0,'vol':1.0,'pitch':0,'emotion':e,
            'duration':None,'language':None,'outputFormat':None,'prompt':None,'referenceVideoList':[]}
        group['request']=request;group['cache_key']=request_key(request)
    if [i for g in groups for i in g['cue_ids']]!=[r['id'] for r in rows]:
        raise ValueError('Speech groups omit or reorder original source')
    inputs={str(folder/'editorial-result.private.json'):digest(folder/'editorial-result.private.json'),
        str(folder/'source-input.private.json'):digest(folder/'source-input.private.json'),
        str(bank_path):digest(bank_path),str(override_path):digest(override_path)}
    return {'project_id':100,'episode':1,'groups':groups,'inputs_sha256':inputs,
        'production_cues':production_cues,
        'max_new_tts':len({g['cache_key'] for g in groups}),'new_clone_count':0,
        'native_listening_passed':False,'speaker_audio_verified':False,
        'grouping_review_required':True,'performance_parameters_are_not_verified_emotion_transfer':True}


def prepare():
    plan=build_plan();path=ROOT/'speech-plan.private.json'
    if path.exists() and read_json(path)!=plan:raise ValueError('Production inputs changed; preserve prior paid plan')
    save_json(path,plan)
    from prepare_review_episode_editorial import srt_time
    body='\n\n'.join(f'{c["id"].split("-",1)[1]}\n{srt_time(c["start"])} --> {srt_time(c["end"])}\n{c["translation"]}' for c in plan['production_cues'])+'\n'
    subtitle=ROOT/'pt-BR-production-candidate.srt'
    if subtitle.exists() and subtitle.read_text(encoding='utf-8')!=body:raise ValueError('Prior production subtitle changed')
    subtitle.write_text(body,encoding='utf-8')
    save_json(ROOT/'progress.private.json',{'stage':'speech_plan_ready_review_pending',
        'groups':len(plan['groups']),'max_new_tts':plan['max_new_tts'],'new_clone_count':0})
    return plan


def wave_evidence(path):
    import wave
    import numpy as np
    if not 0<path.stat().st_size<=32*1024*1024:raise ValueError('Raw WAV file size outside bounds')
    with wave.open(str(path),'rb') as reader:
        channels=reader.getnchannels();width=reader.getsampwidth();rate=reader.getframerate();frames=reader.getnframes()
        count=frames*channels*width
        if (channels not in (1,2) or width not in (1,2,3,4) or not 8000<=rate<=192000
          or not frames or count>32*1024*1024 or frames/rate>600):
            raise ValueError('Generated PCM WAV outside bounds')
        body=reader.readframes(frames)
    if len(body)!=count:raise ValueError('Truncated generated WAV')
    if width==1:samples=np.frombuffer(body,dtype=np.uint8).astype('float64')-128;scale=128
    elif width==3:
        parts=np.frombuffer(body,dtype=np.uint8).reshape(-1,3).astype('int32')
        samples=parts[:,0]|parts[:,1]<<8|parts[:,2]<<16
        samples=np.where(samples&0x800000,samples-0x1000000,samples).astype('float64');scale=8388608
    else:samples=np.frombuffer(body,dtype='<i2' if width==2 else '<i4').astype('float64');scale=2**(8*width-1)
    peak=float(np.max(np.abs(samples)))/scale
    if not np.isfinite(samples).all() or peak<1e-5:raise ValueError('Empty/nonfinite/silent paid audio; never resubmit automatically')
    return {'frames':frames,'channels':channels,'sample_width':width,'sample_rate':rate,'seconds':frames/rate,'peak':peak}


def accepted_task(value):
    if not isinstance(value,dict) or type(value.get('taskId')) is not int or value['taskId']<=0:
        raise ValueError('Unknown paid submission result; reconcile, never resubmit')
    return value['taskId']


def validate_status(value,task):
    if (not isinstance(value,dict) or type(value.get('taskStatus')) is not int
      or value['taskStatus'] not in (0,1,2,3)
      or ('taskId' in value and (type(value['taskId']) is not int or value['taskId']!=task))):
        raise ValueError('Task response identity/status needs reconciliation')
    return value


def read_cache(folder,key,request):
    marker=folder/'request.private.json';submitted=folder/'submission.private.json'
    receipt=folder/'raw-receipt.private.json';wav=folder/'raw.wav';prepared=folder/'raw-receipt.prepared.private.json'
    pending=folder/'submission.private.submission-pending.json';status_path=folder/'task.private.json'
    if not marker.exists():
        if any(p.exists() for p in (submitted,receipt,wav,prepared,pending,status_path,folder/'raw.download.part')):
            raise ValueError('Orphan paid speech evidence; never adopt or submit again')
        return request,None,None
    saved=read_json(marker)
    if (saved['key']!=key or request_key(saved['request'])!=key or folder.name!=key
      or request_key(request)!=key):raise ValueError('Cached request changed')
    request=saved['request'];task=accepted_task(read_json(submitted)) if submitted.exists() else None
    if pending.exists():
        p=read_json(pending)
        if (task is None or p.get('tool')!='generateAudio'
          or p.get('argument_fingerprint')!=fingerprint({'request':request})):
            raise ValueError('Unknown earlier speech submission; no new paid work')
    status=None
    if status_path.exists():
        s=read_json(status_path)
        if task is None or s['task_id']!=task:raise ValueError('Stored task belongs to another submission')
        status=validate_status(s['result'],task)
    def verify(r,path):
        if (task is None or status is None or status['taskStatus']!=2 or r['key']!=key
          or r['task_id']!=task or r['request_fingerprint']!=fingerprint(request)
          or r['status_sha256']!=digest(status_path) or r['bytes']!=path.stat().st_size
          or r['sha256']!=digest(path) or r['wave']!=wave_evidence(path)):
            raise ValueError('Paid raw WAV differs from immutable request/task/receipt')
    if prepared.exists():
        r=read_json(prepared);part=folder/'raw.download.part'
        if receipt.exists():
            if read_json(receipt)!=r:raise ValueError('Prepared and final paid receipts differ')
            verify(r,wav);prepared.unlink()
        else:
            path=wav if wav.exists() else part
            if wav.exists() and part.exists():raise ValueError('Ambiguous prepared raw artifacts')
            verify(r,path)
            if path==part:part.replace(wav)
            prepared.replace(receipt)
    if wav.exists() or receipt.exists():
        r=read_json(receipt);verify(r,wav);return request,task,r
    return request,task,None


def has_project(data,project_id):
    if isinstance(data,dict):
        return any(str(data.get(key))==str(project_id) for key in ('project_id','projectId')) or any(has_project(v,project_id) for v in data.values())
    return isinstance(data,list) and any(has_project(v,project_id) for v in data)


def preflight_cache(requests,project_id=100):
    CACHE.mkdir(parents=True,exist_ok=True)
    markers=list(CACHE.rglob('request.private.json'));known={p.parent for p in markers}
    for name in ('submission.private.json','*.submission-pending.json','raw.wav','raw-receipt.private.json',
                 'raw-receipt.prepared.private.json','task.private.json','raw.download.part'):
        for p in CACHE.rglob(name):
            if p.parent not in known:raise ValueError('Unbound existing paid speech artifact')
    for marker in markers:
        value=read_json(marker);read_cache(marker.parent,value['key'],value['request'])
    ledger_path=CACHE/'submission-attempts.private.json'
    if ledger_path.exists():
        ledger=read_json(ledger_path)
        if ledger['project_id']!=project_id:raise ValueError('Speech attempt ledger belongs to another project')
        for key,attempt in ledger['attempts'].items():
            marker=CACHE/key/'request.private.json'
            if not marker.exists():raise ValueError('Prior paid attempt lost its cache binding')
            value=read_json(marker);req,task,_=read_cache(marker.parent,key,value['request'])
            if (task is None or attempt['request_fingerprint']!=fingerprint(req)
              or ('task_id' in attempt and attempt['task_id']!=task)):
                raise ValueError('Unknown earlier paid attempt; reconcile before all new work')
    # Older matching caches outside this canonical namespace must be reconciled, not bypassed.
    aliases=set()
    for request in requests.values():
        import itertools
        choices=[]
        for name in ('speed','vol','pitch'):
            value=request[name];choices.append((int(value),float(value)) if type(value) in (int,float) and value==int(value) else (value,))
        for values in itertools.product(*choices):
            variant=dict(request)
            for name,value in zip(('speed','vol','pitch'),values):variant[name]=value
            aliases.update((fingerprint(variant),fingerprint({'request':variant})))
    cache_root=CACHE.resolve()
    for name in ('request.private.json','request-fingerprint.json','request-fingerprint.private.json','*.submission-pending.json'):
        for p in Path('output').rglob(name):
            if cache_root in p.resolve().parents:continue
            value=read_json(p)
            own_project=Path(f'output/review-project-{project_id}').resolve() in p.resolve().parents or has_project(value,project_id)
            if p.name.endswith('.submission-pending.json'):
                if own_project or (isinstance(value,dict) and value.get('argument_fingerprint') in aliases):
                    raise ValueError('External unknown project100 speech/clone work requires reconciliation')
            elif isinstance(value,dict):
                req=value.get('request')
                matching=(isinstance(req,dict) and req.get('projectId')==project_id and all(k in req for k in ('speed','vol','pitch')) and request_key(req) in requests)
                if matching or value.get('fingerprint') in aliases:
                    raise ValueError('Matching external paid cache exists; do not duplicate synthesis')
    return {key:read_cache(CACHE/key,key,request) for key,request in requests.items()}


def generate(plan,config,*,expected_scope=(100,1),current_plan_builder=None,max_groups=44):
    approval=read_json(ROOT/'speech-approval.private.json')
    if (approval['plan_sha256']!=digest(ROOT/'speech-plan.private.json')
      or approval['max_new_tts']!=plan['max_new_tts'] or approval['new_clones']!=0
      or approval['speech_groups_approved'] is not True
      or digest(approval['audit_report_path'])!=approval['audit_report_sha256']):
        raise ValueError('Actual finite speech plan review required')
    current=build_plan() if current_plan_builder is None else current_plan_builder()
    if plan!=read_json(ROOT/'speech-plan.private.json') or plan!=current:raise ValueError('Current source or voice bank differs')
    requests={g['cache_key']:g['request'] for g in plan['groups']}
    if ((plan['project_id'],plan['episode'])!=expected_scope or plan['new_clone_count']!=0
      or plan['max_new_tts']!=len(requests) or not 1<=len(requests)<=max_groups
      or any(request_key(request)!=key for key,request in requests.items())):
        raise ValueError('Finite canonical speech request bound differs')
    cached=preflight_cache(requests,plan['project_id'])
    if sum(task is None for _,task,_ in cached.values())>approval['max_new_tts']:
        raise ValueError('New synthesis bound exceeded before client initialization')
    plan_sha=digest(ROOT/'speech-plan.private.json')
    ledger_path=CACHE/'submission-attempts.private.json'
    ledger=read_json(ledger_path) if ledger_path.exists() else {'project_id':plan['project_id'],'attempts':{}}
    prior_attempts=sum(a['origin_plan_sha256']==plan_sha for a in ledger['attempts'].values())
    finished=ROOT/'generation-result.private.json'
    if finished.exists():
        old=read_json(finished)
        if (old['plan_sha256']!=plan_sha or old['new_clone_count']!=0 or old['native_listening_passed'] is not False
          or old['new_submission_attempts']!=prior_attempts
          or [r['group_id'] for r in old['groups']]!=[g['id'] for g in plan['groups']]):
            raise ValueError('Completed speech result scope differs')
        for g,r in zip(plan['groups'],old['groups']):
            req,task,receipt=cached[g['cache_key']]
            if (receipt is None or r['key']!=g['cache_key'] or Path(r['raw_path'])!=CACHE/g['cache_key']/'raw.wav'
              or r['task_id']!=task or r['raw_sha256']!=receipt['sha256']
              or r['request_fingerprint']!=fingerprint(req)):
                raise ValueError('Completed speech result changed; preserve original costs')
        save_json(ROOT/'progress.private.json',{'stage':'grouped_speech_ready_fit_pending','completed':len(plan['groups']),
          'total':len(plan['groups']),'unique_requests':len(requests),'new_submission_attempts':prior_attempts,'new_clone_count':0})
        return
    contexts=threading.local();lock=threading.Lock();submit_lock=threading.Lock();stopped=threading.Event()
    states={g['id']:{'status':'not_started','key':g['cache_key']} for g in plan['groups']}
    completed={};attempts=prior_attempts
    def progress(key,status,**extra):
        with lock:
            for g in plan['groups']:
                if g['cache_key']==key:states[g['id']]={'status':status,'key':key,**extra}
            save_json(ROOT/'progress.private.json',{'stage':'generating_grouped_speech','groups':states,
              'completed':sum(s['status']=='raw_ready' for s in states.values()),'total':len(states),
              'new_submission_attempts':attempts,'max_new_tts':plan['max_new_tts'],'new_clone_count':0})
    def produce(key):
        nonlocal attempts
        folder=CACHE/key;folder.mkdir(parents=True,exist_ok=True)
        try:
            with process_lock(folder/'cache.lock'):
                request,task,receipt=read_cache(folder,key,requests[key]);reused=receipt is not None
                if receipt is None:
                    if task is None and stopped.is_set():raise ValueError('Held after another group failure; no new submission')
                    if not hasattr(contexts,'client'):
                        from mflix_client import Mflix
                        contexts.client=Mflix(config)
                    client=contexts.client
                    if task is None:
                        with submit_lock:
                            if stopped.is_set():raise ValueError('Held after another group failure; no new submission')
                            if attempts>=approval['max_new_tts']:raise ValueError('Paid request cap exhausted')
                            if key in ledger['attempts']:raise ValueError('Earlier attempt reservation exists; never resubmit')
                            if not (folder/'request.private.json').exists():save_json(folder/'request.private.json',{'key':key,'request':request})
                            ledger['attempts'][key]={'request_fingerprint':fingerprint(request),'origin_plan_sha256':plan_sha,'started_at':time.time()}
                            save_json(ledger_path,ledger);attempts+=1;progress(key,'submitting')
                            try:
                                task=accepted_task(safe_submit(client,'generateAudio',{'request':request},folder/'submission.private.json'))
                                ledger['attempts'][key]['task_id']=task;save_json(ledger_path,ledger)
                            except Exception:stopped.set();raise
                    progress(key,'polling_known_task',task_id=task)
                    status_path=folder/'task.private.json';old=read_json(status_path) if status_path.exists() else None
                    if old and validate_status(old['result'],task)['taskStatus']==3:raise ValueError('Known paid task failed; no automatic new attempt')
                    deadline=time.monotonic()+900
                    while True:
                        status=validate_status(client.task(task),task);save_json(status_path,{'task_id':task,'result':status})
                        if status['taskStatus'] in (2,3):break
                        if time.monotonic()>deadline:raise ValueError('Known task pending; only poll this ID, never resubmit')
                        time.sleep(10)
                    if status['taskStatus']!=2:raise ValueError('Paid task failed; no automatic new attempt')
                    url=status.get('resultAudioUrl') or (status.get('resultAudioUrls') or [None])[0]
                    u=urlsplit(url) if isinstance(url,str) else None
                    if u is None or u.scheme!='https' or not u.hostname or u.username or u.password:
                        raise ValueError('No HTTPS generated audio')
                    part=folder/'raw.download.part'
                    if part.exists():part.rename(folder/f'raw.download.previous-{time.time_ns()}.part')
                    size=0
                    try:
                        with client.http.get(url,stream=True,timeout=120,allow_redirects=False,headers={'Accept-Encoding':'identity'}) as response:
                            response.raise_for_status()
                            if response.status_code!=200 or response.headers.get('Content-Encoding','identity') not in ('','identity'):
                                raise ValueError('Unexpected generated audio response')
                            length=response.headers.get('Content-Length');expected=int(length) if length is not None else None
                            if expected is not None and not 0<expected<=32*1024*1024:raise ValueError('Generated length outside bounds')
                            with part.open('wb') as stream:
                                for chunk in response.iter_content(1024*1024):
                                    if size+len(chunk)>32*1024*1024 or (expected is not None and size+len(chunk)>expected):
                                        raise ValueError('Generated body exceeds declared bounds')
                                    stream.write(chunk);size+=len(chunk)
                            if not size or (expected is not None and size!=expected):raise ValueError('Generated body length mismatch')
                    except Exception:raise RuntimeError('Known task audio download failed; private URL omitted') from None
                    receipt={'key':key,'task_id':task,'request_fingerprint':fingerprint(request),
                      'status_sha256':digest(status_path),'bytes':size,'sha256':digest(part),'wave':wave_evidence(part)}
                    save_json(folder/'raw-receipt.prepared.private.json',receipt)
                    part.replace(folder/'raw.wav');(folder/'raw-receipt.prepared.private.json').replace(folder/'raw-receipt.private.json')
                value={'key':key,'raw_path':str(folder/'raw.wav'),'raw_sha256':receipt['sha256'],
                  'task_id':receipt['task_id'],'request_fingerprint':receipt['request_fingerprint'],
                  'seconds':receipt['wave']['seconds'],'reused_completed_audio':reused}
            progress(key,'raw_ready',task_id=receipt['task_id'])
            return value
        except Exception as exc:
            stopped.set();progress(key,'needs_reconciliation',error_type=type(exc).__name__)
            raise
    # Finish already-paid work first; unresolved old audio cannot trigger new spending.
    for keys in ([key for key in requests if cached[key][1] is not None],
                 [key for key in requests if cached[key][1] is None]):
        if stopped.is_set():break
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={pool.submit(produce,key):key for key in keys}
            for future,key in futures.items():
                try:completed[key]=future.result()
                except Exception:pass
    if len(completed)!=len(requests):
        save_json(ROOT/'generation-failure.private.json',{'plan_sha256':digest(ROOT/'speech-plan.private.json'),
          'groups':states,'new_submission_attempts':attempts,'automatic_new_paid_retry':False})
        raise ValueError('Speech groups need reconciliation; paid receipts preserved')
    results=[{'group_id':g['id'],**completed[g['cache_key']]} for g in plan['groups']]
    save_json(ROOT/'generation-result.private.json',{'plan_sha256':digest(ROOT/'speech-plan.private.json'),
      'groups':results,'new_clone_count':0,'native_listening_passed':False,'new_submission_attempts':attempts})
    save_json(ROOT/'progress.private.json',{'stage':'grouped_speech_ready_fit_pending','completed':len(results),
      'total':len(results),'unique_requests':len(requests),'new_submission_attempts':attempts,'new_clone_count':0})

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage',choices=('prepare','generate'),default='prepare')
    parser.add_argument('--mcp-config',type=Path);args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows business execution only')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'production.lock',timeout=0):
        if args.stage=='prepare':prepare()
        else:
            if not args.mcp_config:raise ValueError('Private MCP config required')
            with process_lock(Path('output/paid-production.lock'),timeout=0):generate(read_json(ROOT/'speech-plan.private.json'),args.mcp_config)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        if sys.platform=='win32':
            ROOT.mkdir(parents=True,exist_ok=True)
            old=read_json(ROOT/'progress.private.json') if (ROOT/'progress.private.json').exists() else {}
            save_json(ROOT/'progress.private.json',{**old,'stage':'speech_needs_reconciliation',
              'error_type':type(exc).__name__,'automatic_new_paid_retry':False,'new_clone_count':0})
        raise
