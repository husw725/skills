"""Clone reusable voices, synthesize ordered dialogue, mix backgrounds and copy video."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import uuid
import wave

from mflix_client import Mflix
from translate import fingerprint, read_json, save_json
from process_lock import process_lock

RATE=48000


def run(command):
    r=subprocess.run([str(x) for x in command],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if r.returncode:raise RuntimeError(r.stderr[-2000:] or 'Media command failed')
    return r.stdout


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def probe(path,ffmpeg):
    return json.loads(run([Path(ffmpeg).with_name('ffprobe.exe'),'-v','error','-show_streams','-show_format','-of','json',path]))


def read_audio(path,ffmpeg):
    import numpy as np
    cmd=[str(ffmpeg),'-v','error','-i',str(path),'-vn','-ar',str(RATE),'-ac','1','-f','f32le','pipe:1']
    r=subprocess.run(cmd,capture_output=True)
    if r.returncode:raise RuntimeError('Audio decode failed')
    return np.frombuffer(r.stdout,dtype='<f4').copy()


def trim_edges(samples):
    import numpy as np
    frame=480
    count=len(samples)//frame
    if count<1:return samples,0,0
    rms=np.sqrt(np.mean(samples[:count*frame].reshape(count,frame)**2,axis=1))
    audible=np.flatnonzero(rms>max(0.001, float(rms.max())*.005))
    if not len(audible):raise ValueError('Synthesized audio is silent')
    first=max(0,int(audible[0]*frame)-3840)
    last=min(len(samples),int((audible[-1]+1)*frame)+4800)
    return samples[first:last],first/RATE,(len(samples)-last)/RATE


def write_audio(path,samples):
    import numpy as np
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(RATE)
        w.writeframes((np.clip(samples,-1.,1.)*32767).astype('<i2').tobytes())


def validate_units(units,voices,duration):
    ids=set()
    for u in units:
        if u['id'] in ids:raise ValueError('Duplicate speech unit')
        ids.add(u['id'])
        if not isinstance(u.get('translation'),str) or not u['translation'].strip():raise ValueError('Missing translation')
        if not all(math.isfinite(u[k]) for k in ('start','end')) or not 0<=u['start']<u['end']<=duration+.1:
            raise ValueError('Speech unit outside source timeline')
        if u.get('production_voice') not in voices:raise ValueError('Unknown production voice; annotate before dubbing')
        if u.get('emotion') not in ('auto','happy','sad','angry','fearful','disgusted','surprised','calm','fluent','whisper'):
            raise ValueError('Unsupported MiniMax emotion')


def make_reference(source,segments,destination,ffmpeg):
    if not segments:raise ValueError('Voice clone needs source segments')
    pieces=[]
    for i,(start,end) in enumerate(segments):
        if not 0<=start<end:raise ValueError('Invalid reference segment')
        pieces.append(f'[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]')
    pieces.append(''.join(f'[a{i}]' for i in range(len(segments)))+f'concat=n={len(segments)}:v=0:a=1[out]')
    run([ffmpeg,'-v','error','-y','-i',source,'-filter_complex',';'.join(pieces),'-map','[out]',
         '-ar','44100','-ac','1','-c:a','pcm_s16le',destination])
    p=probe(destination,ffmpeg);duration=float(p['format']['duration'])
    if not 10<=duration<=300 or Path(destination).stat().st_size>20*1024*1024:
        raise ValueError('Cloning reference must be 10–300 seconds and <=20MB')
    return duration


def safe_submit(client,name,arguments,path):
    """An unresolved submission may have been charged; never retry it automatically."""
    with process_lock(path.with_suffix('.lock')):
        return _safe_submit(client,name,arguments,path)


def _safe_submit(client,name,arguments,path):
    pending=path.with_suffix('.submission-pending.json')
    if path.exists():return read_json(path)
    if pending.exists():raise RuntimeError(f'Ambiguous earlier submission: inspect {pending.name} before retry')
    save_json(pending,{'tool':name,'argument_fingerprint':fingerprint(arguments),'started_at':time.time()})
    result=client.call(name,arguments)
    save_json(path,result)
    pending.unlink()
    return result


def ensure_voices(plan, assets, root, client, ffmpeg):
    """Serialize all clones against the series bank, including receipt recovery."""
    bank_path=Path(plan['voice_bank'])
    with process_lock(bank_path.with_suffix('.lock')):
        bank=read_json(bank_path) if bank_path.exists() else {'schema_version':1,'voices':{}}
        if bank.get('project_id',plan['project_id'])!=plan['project_id']:
            raise ValueError('Voice bank belongs to another project')
        bank['project_id']=plan['project_id']
        for name,reference in plan['voices'].items():
            if name in bank['voices']:continue
            if reference.get('existing_voice_id'):
                record={'voice_id':reference['existing_voice_id'],'source':'prior-smoke-test','listening_verified':False}
            else:
                # Receipt location is independent of episode, so a crash cannot
                # cause a later episode to pay for the same role again.
                role_key=fingerprint({'project':plan['project_id'],'role':name})
                private_path=bank_path.parent/'voice-clone-receipts'/f'{role_key}.private.json'
                pending=private_path.with_suffix('.submission-pending.json')
                legacy=[]
                for folder in bank_path.parent.glob('episode-*/dub-*'):
                    candidate=folder/f'clone-{name}.private.json'
                    if candidate.exists():legacy.append(read_json(candidate))
                    if candidate.with_suffix('.submission-pending.json').exists():
                        raise RuntimeError(f'Ambiguous earlier clone for {name}; inspect saved receipt before retry')
                if private_path.exists():legacy.append(read_json(private_path))
                if pending.exists():
                    raise RuntimeError(f'Ambiguous earlier clone for {name}; inspect saved receipt before retry')
                ids={r['voiceId'] for r in legacy}
                if len(ids)>1:raise ValueError(f'Conflicting clone receipts for {name}; reconcile voice bank')
                if legacy:
                    result=legacy[0]
                    record={'voice_id':result['voiceId'],'source':'recovered-clone-receipt','listening_verified':False}
                else:
                    ref=root/f'reference-{name}.wav'
                    ref_duration=make_reference(assets['source_audio'],reference['segments_seconds'],ref,ffmpeg)
                    url=client.upload(ref)
                    voice_id='studio_carmilla_'+name.lower()+'_'+uuid.uuid4().hex[:12]
                    result=safe_submit(client,'uploadMiniMaxVoice',{'request':{'projectId':plan['project_id'],
                        'referenceAudioUrl':url,'voiceId':voice_id}},private_path)
                    record={'voice_id':result['voiceId'],'reference_sha256':digest(ref),'reference_seconds':ref_duration,
                            'source_episode':plan['episode'],'listening_verified':False}
            bank['voices'][name]=record
            save_json(bank_path,bank)
            print('Voice ready',name,flush=True)
        return bank


def wait_task(client,task_id,state_file):
    state=read_json(state_file) if state_file.exists() else {'task_id':task_id,'last_poll':0}
    if state.get('result',{}).get('taskStatus') in (2,3):return state['result']
    delay=max(0,10-(time.time()-state.get('last_poll',0)))
    if delay:time.sleep(delay)
    state['last_poll']=time.time();save_json(state_file,state)
    result=client.task(task_id);state['result']=result;save_json(state_file,state)
    return result


def tts_request(unit,voice_id,project_id,speed,emotion):
    return {'projectId':project_id,'model':'speech-2.8-hd','text':unit['translation'],
            'voiceId':voice_id,'referenceAudioList':[],'referenceVideoList':[],
            'languageBoost':'Portuguese','format':'wav','speed':speed,
            'vol':0.7 if unit['emotion']=='whisper' and emotion=='calm' else 1.0,'pitch':0,
            'emotion':emotion,'duration':None,'prompt':None}


def validate_synthesis_cache(folder,unit,voice_id,project_id):
    signature=fingerprint({'unit':unit,'voice_id':voice_id,'project_id':project_id,
                           'settings':tts_request(unit,voice_id,project_id,float(unit.get('speed',1.)),unit['emotion'])})
    marker=folder/'synthesis-input.json'
    if marker.exists() and read_json(marker)['fingerprint']!=signature:
        raise ValueError('Synthesis voice or inputs changed; inspect existing tasks, no automatic regeneration')
    cached=folder/'result.json'
    saved=read_json(cached) if cached.exists() else None
    if saved:
        expected={'id':unit['id'],'cue_ids':unit['cue_ids'],'voice':unit['production_voice'],
                  'voice_id':voice_id,'start':unit['start'],'end':unit['end'],
                  'translation':unit['translation'],'requested_emotion':unit['emotion']}
        if any(saved.get(k)!=v for k,v in expected.items()):
            raise ValueError('Cached synthesis voice or inputs differ; inspect before regenerating')
        if saved.get('input_fingerprint') and saved['input_fingerprint']!=signature:
            raise ValueError('Cached synthesis settings differ; inspect before regenerating')
    if not marker.exists() and not (saved and saved.get('input_fingerprint')):
        attempt=folder/'attempt-0.json'
        if attempt.exists():
            emotions=[unit['emotion']]
            if unit['emotion']=='whisper':emotions.append('calm')
            permitted={fingerprint(tts_request(unit,voice_id,project_id,float(unit.get('speed',1.)),emotion)) for emotion in emotions}
            if read_json(attempt).get('request_fingerprint') not in permitted:
                raise ValueError('Legacy synthesis request differs; inspect before resuming')
        elif saved or list(folder.glob('submission-*.json')):
            raise ValueError('Legacy synthesis receipt lacks input binding; inspect before resuming')
    if not marker.exists():save_json(marker,{'fingerprint':signature})
    return signature,saved


def synthesize(client,unit,voice_id,root,project_id,ffmpeg):
    folder=root/unit['id'];folder.mkdir(parents=True,exist_ok=True)
    signature,saved=validate_synthesis_cache(folder,unit,voice_id,project_id)
    if saved:
        if Path(saved['fitted_path']).exists() and digest(saved['fitted_path'])==saved['fitted_sha256']:
            return saved
    target=unit['end']-unit['start']
    speed=float(unit.get('speed',1.0))
    attempts=[]
    actual_emotion=unit['emotion']
    # Runtime confirmed that speech 2.8 rejects whisper despite the tool catalog.
    # Legacy attempt records are still replayed faithfully to preserve checkpoints.
    if actual_emotion=='whisper' and not (folder/'attempt-0.json').exists():actual_emotion='calm'
    for attempt in range(3):
        request=tts_request(unit,voice_id,project_id,speed,actual_emotion)
        path=folder/f'attempt-{attempt}.json'
        if path.exists():
            accepted=read_json(path)
            if accepted['request_fingerprint']!=fingerprint(request):raise ValueError('TTS checkpoint does not match request')
        else:
            result=safe_submit(client,'generateAudio',{'request':request},folder/f'submission-{attempt}.json')
            accepted={'request_fingerprint':fingerprint(request),'task_id':result['taskId'],'speed':speed}
            save_json(path,accepted)
        state_file=folder/f'task-{attempt}.private.json'
        while True:
            result=wait_task(client,accepted['task_id'],state_file)
            if result['taskStatus'] in (2,3):break
            print(f"{unit['id']} task {accepted['task_id']} running",flush=True)
        if result['taskStatus']==3:
            if actual_emotion=='whisper' and "don't support whisper" in str(result.get('taskMessage','')):
                attempts.append({'task_id':accepted['task_id'],'status':'failed','reason':'Service does not support whisper for speech 2.8'})
                actual_emotion='calm'
                print(unit['id'],'whisper rejected; using calm at lower volume',flush=True)
                continue
            raise RuntimeError(f'Generation task {accepted["task_id"]} failed; inspect private task record')
        url=result.get('resultAudioUrl') or (result.get('resultAudioUrls') or [None])[0]
        if not isinstance(url,str) or not url.startswith('https://'):raise RuntimeError('Task has no HTTPS output audio')
        original=folder/f'original-{attempt}.wav'
        if not original.exists():
            import requests
            for download_attempt in range(3):
                try:
                    response=client.http.get(url,timeout=90)
                    response.raise_for_status();audio=response.content
                    expected=response.headers.get('Content-Length')
                    if expected and len(audio)!=int(expected):raise requests.ConnectionError('Incomplete audio response')
                    original.write_bytes(audio)
                    break
                except requests.RequestException:
                    if download_attempt==2:raise RuntimeError(f"{unit['id']} audio download failed; saved task can resume") from None
                    time.sleep(2**download_attempt)
        samples=read_audio(original,ffmpeg);samples,leading,trailing=trim_edges(samples)
        measured=len(samples)/RATE
        attempts.append({'task_id':accepted['task_id'],'speed':speed,'duration_seconds':measured,
                         'trimmed_leading_seconds':leading,'trimmed_trailing_seconds':trailing})
        ratio=measured/target
        if ratio<=1.25 or attempt==2 or speed>=1.6:break
        speed=round(min(1.6,max(speed+.1,speed*ratio/1.1)),2)
    trimmed=folder/'trimmed.wav';write_audio(trimmed,samples)
    fitted=folder/'fitted.wav'
    factor=max(1.0,measured/target)
    # Do not truncate spoken words. Excessive fitting remains visible in the report.
    run([ffmpeg,'-v','error','-y','-i',trimmed,'-af',f'atempo={factor:.8f}',
         '-ar',str(RATE),'-ac','1','-c:a','pcm_s16le',fitted])
    fitted_samples=read_audio(fitted,ffmpeg)
    if len(fitted_samples)>math.ceil(target*RATE)+960:
        raise RuntimeError('Fitted audio exceeds assigned window')
    if len(fitted_samples)>math.ceil(target*RATE):
        extra=fitted_samples[math.ceil(target*RATE):]
        import numpy as np
        if np.max(np.abs(extra))>.003:raise RuntimeError('Fit would cut audible words at cue end')
        fitted_samples=fitted_samples[:math.ceil(target*RATE)];write_audio(fitted,fitted_samples)
    item={'id':unit['id'],'cue_ids':unit['cue_ids'],'voice':unit['production_voice'],'voice_id':voice_id,
          'start':unit['start'],'end':unit['end'],'translation':unit['translation'],'emotion':actual_emotion,
          'requested_emotion':unit['emotion'],'emotion_fallback':actual_emotion!=unit['emotion'],
          'attempts':attempts,'atempo_factor':factor,'fitted_duration_seconds':len(fitted_samples)/RATE,
          'timing_quality_review_required':factor>1.25 or speed>1.4,
          'fitted_path':str(fitted),'fitted_sha256':digest(fitted),'input_fingerprint':signature}
    save_json(folder/'result.json',item)
    return item


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--mcp-config',required=True,type=Path)
    parser.add_argument('--ffmpeg',required=True,type=Path)
    args=parser.parse_args()
    if sys.platform!='win32':parser.error('Business execution is Windows-only')
    plan=read_json(args.plan)
    # Includes receipt writes and final rendering: accidentally starting the same
    # episode twice must never race a paid TTS submission or overwrite its output.
    with process_lock(Path(plan['output_dir']).parent/'production.lock',timeout=0):
        render_episode(args,plan)


def render_episode(args,plan):
    assets={k:Path(v) for k,v in plan['assets'].items()}
    for k in ('video','bgm','sfx','source_audio'):
        if not assets[k].is_file():raise ValueError('Missing '+k)
    root=Path(plan['output_dir']);root.mkdir(parents=True,exist_ok=True)
    video_meta=probe(assets['video'],args.ffmpeg);duration=float(video_meta['format']['duration'])
    units=plan['units'];validate_units(units,plan['voices'],duration)
    signature=fingerprint({'plan':plan,'source_sha256':{k:digest(p) for k,p in assets.items()}})
    signature_path=root/'input-fingerprint.json'
    if signature_path.exists() and read_json(signature_path)['fingerprint']!=signature:
        raise ValueError('Episode input changed; use a new output directory')
    save_json(signature_path,{'fingerprint':signature})
    bank_path=Path(plan['voice_bank'])
    client=Mflix(args.mcp_config)
    bank=ensure_voices(plan,assets,root,client,args.ffmpeg)
    from concurrent.futures import ThreadPoolExecutor
    import threading
    workers=int(plan.get('tts_workers',3))
    if not 1<=workers<=3:raise ValueError('Use 1–3 TTS workers per episode')
    progress_lock=threading.Lock();completed=[u["id"] for u in units if (root/"utterances"/u["id"]/"result.json").exists()]
    def produce(unit):
        local_client=Mflix(args.mcp_config)
        result=synthesize(local_client,unit,bank['voices'][unit['production_voice']]['voice_id'],root/'utterances',plan['project_id'],args.ffmpeg)
        with progress_lock:
            if unit['id'] not in completed:completed.append(unit['id'])
            save_json(root/'progress.json',{'episode':plan['episode'],'completed_units':completed,'total_units':len(units),'updated_at':time.time()})
            print(f'Episode {plan["episode"]}: completed {len(completed)}/{len(units)} {unit["id"]}',flush=True)
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(produce,unit) for unit in units]
        results=[future.result() for future in futures]
    import numpy as np
    size=math.ceil(duration*RATE);dialogue=np.zeros(size,dtype=np.float32)
    for result in results:
        samples=read_audio(Path(result['fitted_path']),args.ffmpeg);start=round(result['start']*RATE)
        if start+len(samples)>size:raise ValueError('Dialogue extends past video')
        dialogue[start:start+len(samples)]+=samples
    dialogue_file=root/'dialogue-ptBR.wav';write_audio(dialogue_file,dialogue)
    combined=root/'mix-ptBR.wav'
    run([args.ffmpeg,'-v','error','-y','-i',dialogue_file,'-i',assets['bgm'],'-i',assets['sfx'],
         '-filter_complex',f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[2:a]apad,atrim=duration={duration}[s];[d][b][s]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
         '-map','[out]','-ar',str(RATE),'-ac','2','-c:a','pcm_s16le',combined])
    final=root/f'Carmilla_EP{int(plan["episode"]):02d}_pt-BR.mp4'
    run([args.ffmpeg,'-v','error','-y','-i',assets['video'],'-i',combined,'-map','0:v:0','-map','1:a:0',
         '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',final])
    run([args.ffmpeg,'-v','error','-xerror','-i',final,'-f','null','-'])
    hashes=[]
    for path in (assets['video'],final):
        hashes.append(run([args.ffmpeg,'-v','error','-i',path,'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip())
    if hashes[0]!=hashes[1]:raise RuntimeError('Output video payload differs from original')
    final_meta=probe(final,args.ffmpeg)
    report={'episode':plan['episode'],'status':'rendered_draft','output':str(final),'output_sha256':digest(final),
            'video_payload_identical':True,'duration_seconds':float(final_meta['format']['duration']),
            'source_duration_seconds':duration,'utterances':results,'voice_bank':str(bank_path),
            'source_audio_in_output':False,'background_tracks':['bgm','sfx'],'timing_fitted':True,
            'native_ptBR_listening_reviewed':False,'speaker_audio_verified':False,
            'timing_quality_review_count':sum(x['timing_quality_review_required'] for x in results),
            'warnings':plan.get('warnings',[]),'completed_at':time.time()}
    save_json(root/'render-report.json',report)
    assert read_json(root/'render-report.json')['video_payload_identical']
    print('RENDERED',final,'timing_review',report['timing_quality_review_count'],flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('FAILED',type(exc).__name__,str(exc),file=sys.stderr,flush=True);sys.exit(1)
