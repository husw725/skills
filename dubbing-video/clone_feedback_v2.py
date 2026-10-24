"""Bounded October 24 follow-up: five new requests, three unchanged references."""
import argparse
import copy
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

from translate import read_json, save_json, fingerprint
from dub_episode import digest, read_audio, probe, RATE
from process_lock import process_lock
from cartesia_pilot import bind
from repair_episode_feedback import generate
from mflix_client import Mflix
from rerun_carmilla_season import paid_audio_folder, paid_cache_roots
import clone_feedback_pilot as prior

ROOT = Path('output/clone-feedback-20261024')
PRIOR = Path('output/clone-feedback-20261021')
IPA = '(ˈkõmu)?'
SPECS = [
 ('C1','father-como-natural',None,None,None,'REFERENCE: previous Como, speed 1.0'),
 ('C2','father-como-slower',None,None,None,'REFERENCE: previous Como, speed 0.9; ASR uncertainty'),
 ('C3','father-como-natural',IPA,1.0,'surprised','NEW: dictionary IPA, speed 1.0; pronunciation experiment'),
 ('C4','father-como-natural',IPA,.95,'surprised','NEW: same dictionary IPA, speed 0.95'),
 ('R1','irina-sanctuary',None,None,None,'REFERENCE: previous full sentence, calm, speed 0.9'),
 ('R2','irina-sanctuary',None,1.0,'calm','NEW: correct spelling, calm, normal rate'),
 ('R3','irina-sanctuary',None,1.05,'calm','NEW: correct spelling, calm, speed 1.05'),
 ('R4','irina-sanctuary',None,1.0,'auto','NEW: correct spelling, auto diagnostic; acting not approved'),
]
NAME = 'Carmilla | Existing clone pt-BR | Como-ruindo follow-up v2'


def expected_manifest():
    old = read_json(PRIOR/'manifest.private.json'); prior.validate(old)
    result = read_json(PRIOR/'generation-result.private.json')['results']
    sources = {c['id']:c for c in old['cases']}
    rows=[]
    for cid, source_id, text, speed, emotion, label in SPECS:
        source=sources[source_id]; req=copy.deepcopy(source['request'])
        if speed is not None:
            req.update(text=text or req['text'], speed=speed, emotion=emotion)
        rows.append({'id':cid,'source_case':source_id,'caption':source['caption'],
          'request':req,'label':label,'reference':speed is None,
          'source_window_seconds':source['end']-source['start'],
          'production_voice':source['production_voice'],
          'source_request_fingerprint':fingerprint(source['request']),
          'source_audio':result[fingerprint(source['request'])]})
    evidence=Path('output/review-feedback/2026-10-24')
    inputs={str(p):digest(p) for p in [PRIOR/'manifest.private.json',PRIOR/'generation-result.private.json',
      PRIOR/'publication-result.private.json',evidence/'asset-2731-page-1.private.json',
      evidence/'materials.private.json',evidence/'pronunciation-research.private.json']}
    return {'cases':rows,'inputs':inputs,'project_id':59,'review_project_id':148,
      'paid_request_limit':5,'new_clone_count':0,'comment_ids':[8153,8154],
      'ipa_source':'https://kotobank.jp/ptjaword/como',
      'ipa_status':'Sourced dictionary transcription, experimental synthesis; not unique Brazilian gold pronunciation',
      'policy':'Unchanged actor clone IDs; raw dry audition only; original SRT/plans/episodes preserved; no human recording required'}


def validate(m):
    if m != expected_manifest(): raise ValueError('Fixed follow-up scope or physical source changed')
    if read_json(ROOT/'manifest-fingerprint.json')['fingerprint']!=fingerprint(m):
        raise ValueError('Follow-up manifest not bound')
    if len({fingerprint(c['request']) for c in m['cases']})!=8:
        raise ValueError('Expected eight distinct fixed requests')


def prepare():
    m=expected_manifest(); bind(ROOT/'manifest-fingerprint.json',m)
    path=ROOT/'manifest.private.json'
    if path.exists() and read_json(path)!=m:raise ValueError('Do not overwrite a different audition')
    if not path.exists():save_json(path,m)
    validate(m);print('FOLLOWUP_PREPARED',len(m['cases']),flush=True)


def completed(folder,req):
    marker=read_json(folder/'request-fingerprint.json')
    accepted=read_json(folder/'submission.private.json')
    receipt=read_json(folder/'audio-receipt.json');path=folder/'original.wav'
    if (marker['fingerprint']!=fingerprint(req) or receipt['task_id']!=accepted['taskId']
      or receipt['sha256']!=digest(path)):raise ValueError('Paid audio binding differs')
    return path,receipt


def preflight(m):
    # Unknown submissions must block even when the next candidate has different text.
    for root in [PRIOR/'requests', ROOT/'requests',Path('output/drama-01')]:
        for pending in root.rglob('*.submission-pending.json'):
            accepted=pending.with_name(pending.name.removesuffix('.submission-pending.json')+'.json')
            if not accepted.exists() or not read_json(accepted).get('taskId'):
                raise ValueError('Unknown paid submission: reconcile before any new request')
    selected={}
    for c in m['cases']:
        req=c['request'];key=fingerprint(req);target=ROOT/'requests'/key;matches=[]
        episode=5 if c['id'].startswith('C') else 32
        for root in paid_cache_roots():
            # Checking all 32 episode caches also prevents cross-episode duplicate payment.
            for n in range(1,33):
                found=paid_audio_folder(n,req,target,root)
                if found!=target:matches.append(found)
        for root in [PRIOR/'requests',ROOT/'requests',Path('output/drama-01')]:
            for marker in root.rglob('request-fingerprint.json'):
                if read_json(marker).get('fingerprint')==key:matches.append(marker.parent)
        folder=matches[0] if matches else target
        if c['reference'] and folder==target:raise ValueError('Reference must reuse completed prior audio')
        if folder!=target or (folder/'audio-receipt.json').exists():completed(folder,req)
        elif (folder/'submission.private.json').exists():
            accepted=read_json(folder/'submission.private.json')
            if not accepted.get('taskId'):raise ValueError('Existing task needs reconciliation')
        selected[key]=folder
    save_json(ROOT/'cache-preflight.private.json',{'selected':{k:str(v) for k,v in selected.items()},
      'max_new_requests':5,'new_clone_count':0})
    return selected


def synthesize(m,config,ffmpeg):
    validate(m);selected=preflight(m);results={};client=None;new_count=0
    for c in m['cases']:
        req=c['request'];key=fingerprint(req);folder=selected[key]
        reused=(folder/'audio-receipt.json').exists()
        if reused:path,receipt=completed(folder,req)
        else:
            if c['reference']:raise ValueError('Never synthesize a reference')
            if client is None:client=Mflix(config)
            if not (folder/'submission.private.json').exists():new_count+=1
            if new_count>5:raise ValueError('Paid request cap exceeded')
            path,receipt=generate(client,req,folder)
        duration=len(read_audio(path,ffmpeg))/RATE
        results[key]={'path':str(path),'sha256':digest(path),'task_id':receipt['task_id'],
          'request':req,'duration_seconds':duration,'prior_receipt_reused':reused}
        save_json(ROOT/'generation-progress.private.json',results)
        print('FOLLOWUP_AUDIO_READY',c['id'],round(duration,3),'REUSED' if reused else 'NEW',flush=True)
    save_json(ROOT/'generation-result.private.json',{'results':results,'new_clone_count':0})


def generated(m):
    g=read_json(ROOT/'generation-result.private.json')['results']
    if set(g)!={fingerprint(c['request']) for c in m['cases']}:raise ValueError('Incomplete generation')
    for c in m['cases']:
        r=g[fingerprint(c['request'])]
        if r['request']!=c['request'] or digest(r['path'])!=r['sha256']:raise ValueError('Audio changed')
        folder=Path(r['path']).parent;completed(folder,c['request'])
        if c['reference'] and r['sha256']!=c['source_audio']['sha256']:raise ValueError('Reference changed')
    return g


def render(m,ffmpeg):
    validate(m);g=generated(m);report_path=ROOT/'reel-report.private.json'
    output=ROOT/'Carmilla_como_ruindo_followup_v2.mp4'
    if report_path.exists():
        report=read_json(report_path)
        if report['output_sha256']!=digest(output) or report['manifest_sha256']!=digest(ROOT/'manifest.private.json'):
            raise ValueError('Existing reel differs; refuse overwrite')
        print('FOLLOWUP_REEL_REUSED',flush=True);return
    root=ROOT/'reel';root.mkdir(exist_ok=True);clips=[]
    for c in m['cases']:
        r=g[fingerprint(c['request'])];duration=max(4,r['duration_seconds']+1)
        caption=c['caption'].replace('…','...')
        lines=[f'{c["id"]} | {c["production_voice"]}',caption,c['label'],
          'Same existing clone voice ID | raw dry audio, no timing fit',
          'Please comment with C1-C4 / R1-R4; compare pronunciation AND acting',
          'Experimental candidate; pt-BR pronunciation not yet approved']
        text='\\N\\N'.join(lines[:3])+'\\N'+'\\N'.join(lines[3:])
        ass=root/f'{c["id"]}.ass'
        ass.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n[V4+ Styles]\n'
          'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
          'Style: Default,Arial,30,&H00FFFFFF,&H00FFFFFF,&H00151A25,&H00151A25,0,0,0,0,100,100,0,0,1,1,0,5,60,60,40,1\n[Events]\n'
          'Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
          f'Dialogue: 0,0:00:00.00,0:10:00.00,Default,,0,0,0,,{text}\n',encoding='utf-8-sig')
        clip=root/f'{c["id"]}.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x151a25:s=1280x720:r=20',
          '-i',str(Path(r['path']).resolve()),'-vf',f'ass={ass.name}','-af','adelay=500,apad','-t',str(duration),
          '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-b:a','128k',clip.name],cwd=root,check=True,capture_output=True)
        clips.append({'case_id':c['id'],'path':str(clip),'sha256':digest(clip),'duration_seconds':duration,
          'audio_sha256':r['sha256'],'over_source_window':r['duration_seconds']>c['source_window_seconds']})
    listing=root/'concat.txt';listing.write_text(''.join(f"file '{Path(c['path']).name}'\n" for c in clips),encoding='utf-8')
    subprocess.run([str(ffmpeg),'-v','error','-y','-f','concat','-safe','0','-i',str(listing.resolve()),'-c','copy','-movflags','+faststart',str(output.resolve())],check=True,capture_output=True)
    report={'output_sha256':digest(output),'manifest_sha256':digest(ROOT/'manifest.private.json'),
      'generation_sha256':digest(ROOT/'generation-result.private.json'),'clips':clips,'case_count':8,
      'duration_seconds':float(probe(output,ffmpeg)['format']['duration']),'new_clone_count':0,
      'native_listening_passed':False,'episode_replaced':False}
    save_json(report_path,report);print('FOLLOWUP_REEL_READY',report['duration_seconds'],flush=True)


def screen(m,ffmpeg):
    from faster_whisper import WhisperModel
    import numpy as np
    validate(m);g=generated(m);local=Path('output/tools/source-asr-models/large-v3')
    verified=read_json(local/'verified.json');official=read_json(local/'official-source.json')
    expected=next(f['lfs']['sha256'] for f in official['siblings'] if f['rfilename']=='model.bin')
    if (verified.get('official_hashes_verified') is not True or verified.get('repo')!='Systran/faster-whisper-large-v3'
      or verified['revision']!=official['revision'] or digest(local/'model.bin')!=expected):raise ValueError('ASR source changed')
    model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
    decoding={'language':'pt','beam_size':5,'temperature':0,'condition_on_previous_text':False,'vad_filter':False};rows=[]
    for c in m['cases']:
        r=g[fingerprint(c['request'])];target=ROOT/'content-screening'/f'{c["id"]}.private.json'
        if target.exists():
            record=read_json(target)
            if (record['audio_sha256']!=r['sha256'] or record['decoding']!=decoding
              or record['expected_text']!=c['caption']):raise ValueError('Screening basis changed')
        else:
            audio=subprocess.run([str(ffmpeg),'-v','error','-i',r['path'],'-f','f32le','-ar','16000','-ac','1','pipe:1'],check=True,capture_output=True)
            segments,_=model.transcribe(np.frombuffer(audio.stdout,dtype='<f4'),**decoding)
            record={'case_id':c['id'],'audio_sha256':r['sha256'],'expected_text':c['caption'],
              'asr_transcript':' '.join(s.text.strip() for s in segments),'decoding':decoding,
              'model_revision':verified['revision'],'native_listening_passed':False}
            save_json(target,record)
        rows.append(record);print('FOLLOWUP_SCREENED',c['id'],flush=True)
    save_json(ROOT/'content-screening.private.json',{'results':rows,'native_listening_passed':False})


def publish(m,config):
    from publish_review import materials,register,check_matches
    from notify_season_complete import verify_delivery
    validate(m);g=generated(m);report=read_json(ROOT/'reel-report.private.json')
    path=ROOT/'Carmilla_como_ruindo_followup_v2.mp4';sha=digest(path)
    if (report['output_sha256']!=sha or report['case_count']!=8 or len(report['clips'])!=8
      or report['manifest_sha256']!=digest(ROOT/'manifest.private.json')
      or report['generation_sha256']!=digest(ROOT/'generation-result.private.json')
      or report['new_clone_count']!=0 or report['episode_replaced']):raise ValueError('Unverified reel')
    screened=read_json(ROOT/'content-screening.private.json')['results']
    if len(screened)!=8:raise ValueError('Screening incomplete')
    for c,r,clip in zip(m['cases'],screened,report['clips']):
        a=g[fingerprint(c['request'])]
        if (r['case_id']!=c['id'] or r['audio_sha256']!=a['sha256'] or r['expected_text']!=c['caption']
          or clip['case_id']!=c['id'] or clip['audio_sha256']!=a['sha256'] or digest(clip['path'])!=clip['sha256']):raise ValueError('Artifact binding differs')
    client=Mflix(config);rows=materials(client,148)
    base=read_json('output/subtitle-review-update-20261020/live-before.private.json')
    verify_delivery({'all_32_published':True,'published':base['published']},rows)
    old=read_json(PRIOR/'publication-result.private.json');oldrow=next(r for r in rows if r['assetId']==2731)
    if oldrow['url']!=old['url'] or oldrow['name']!=old['name'] or oldrow['version']!=1:raise ValueError('Prior audition changed')
    state=ROOT/'review-upload.private.json'
    if state.exists():
        uploaded=read_json(state)
        if uploaded['sha256']!=sha:raise ValueError('Uploaded content changed')
    else:
        signed=client.call('createFilePresignedUrl',{'originalFileName':path.name})
        if not isinstance(signed,str) or not signed.startswith('https://'):raise ValueError('Expected HTTPS upload')
        uploaded={'sha256':sha,'signed_url':signed,'url':signed.split('?')[0],'status':'uploading'};save_json(state,uploaded)
    if uploaded['status']!='uploaded':
        body=path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('Upload bytes changed')
        try:response=client.http.put(uploaded['signed_url'],data=body,timeout=120);response.raise_for_status()
        except Exception:raise RuntimeError('Upload failed; checkpoint retained, URL omitted') from None
        uploaded['status']='uploaded';save_json(state,uploaded)
    norm=lambda s:re.sub(r'[^\w]+','',unicodedata.normalize('NFC',s).casefold())
    note=('基于2731评论8153/8154的第二轮定点试听。C1/C2为上轮como正常/慢读原音频复用；C3/C4为有词典来源的IPA实验，1.0/0.95。'
      'R1为上轮ruindo整句0.9复用；R2/R3为原句calm1.0/1.05，R4为auto1.0诊断。请明确按C1-C4/R1-R4选最佳或都不合适，并评价发音、音色与表演。'
      '评论未指定上轮哪个B更好，故保留两个como基准，不冒称已验收。沿用同Father/Irina既有克隆，0新clone；只5个新增请求，其余3复用。'
      '字幕仍正确拼写，IPA只在C3/C4合成层。未取得评审私人录音或ruindo标准录音，未训练模型。未改原32集/SRT或2731。'
      '全部为raw干声、无对时，无BGM；新发音/巴西口音/演技未获母语验收。auto不等于情绪迁移。')
    for r in screened:
        if norm(r['expected_text'])!=norm(r['asr_transcript']):note+=f'\nASR疑点非确证错误 {r["case_id"]}: 目标「{r["expected_text"]}」/转写「{r["asr_transcript"]}」'
    over=[c['case_id'] for c in report['clips'] if c['over_source_window']]
    note+=f'\n原窗超时候选: {", ".join(over) or "无"}。不能直接替换。\nIPA来源: {m["ipa_source"]}\nSHA256: {sha}'
    spec={'projectId':148,'gateType':'FINAL_CUT','name':f'{NAME} | {sha[:12]}','url':uploaded['url'],
      'tags':['Carmilla','pt-BR','existing-clone','audition','v2'],'durationSeconds':round(report['duration_seconds']),'note':note}
    ledgerpath=ROOT/'review-ledger.private.json';ledger=read_json(ledgerpath) if ledgerpath.exists() else {'items':{}}
    asset=register(client,spec,ledger,ledgerpath);rows=materials(client,148);row=check_matches(rows,spec)
    verify_delivery({'all_32_published':True,'published':base['published']},rows)
    after=next(r for r in rows if r['assetId']==2731)
    if after!=oldrow or row['assetId']!=asset or row['note']!=note:raise ValueError('Review readback changed')
    try:response=client.http.get(uploaded['url'],timeout=90);response.raise_for_status()
    except Exception:raise RuntimeError('Public verification failed; registration retained') from None
    if hashlib.sha256(response.content).hexdigest()!=sha:raise ValueError('Public content differs')
    save_json(ROOT/'publication-result.private.json',{'asset_id':asset,'project_id':148,'name':spec['name'],
      'url':uploaded['url'],'sha256':sha,'verified_at':time.time(),'new_clone_count':0,
      'original_32_verified':True,'prior_2731_retained':True,'native_listening_passed':False})
    print('FOLLOWUP_REVIEW_VERIFIED',asset,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True,choices=['prepare','preflight','generate','render','screen','publish'])
    p.add_argument('--mcp-config',type=Path);p.add_argument('--ffmpeg',type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Execute business stages on Windows')
    ROOT.mkdir(parents=True,exist_ok=True)
    # Screening may run in parallel with render; paid calls/publication never overlap stages.
    with process_lock(ROOT/('screening.lock' if a.stage=='screen' else 'pilot.lock'),timeout=0):
        if a.stage=='prepare':prepare();return
        m=read_json(ROOT/'manifest.private.json');validate(m)
        if a.stage=='preflight':preflight(m);print('FOLLOWUP_CACHE_PREFLIGHT_OK',flush=True)
        elif a.stage=='generate':synthesize(m,a.mcp_config,a.ffmpeg)
        elif a.stage=='render':render(m,a.ffmpeg)
        elif a.stage=='screen':screen(m,a.ffmpeg)
        else:publish(m,a.mcp_config)


if __name__=='__main__':main()
