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

ROOT=Path('output/review-project-100/episode-01/audio-production-20261031')
CACHE=Path('output/review-project-100/paid-speech-cache')


def request_key(request):
    canonical=dict(request)
    for key in ('speed','vol','pitch'):
        value=canonical[key]
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
    groups=[]
    for row,cue in zip(rows,result['candidate']['cues']):
        role=cue['script_role']
        if role not in bank['voices']:raise ValueError('Unresolved source role; never substitute another voice')
        if groups and groups[-1]['role']==role and row['start']-groups[-1]['end']<=1.25:
            group=groups[-1];group['end']=max(group['end'],row['end']);group['cue_ids'].append(row['id'])
            group['text']+=' '+cue['translation'];group['script_intents'].append(cue['emotion_intent'])
        else:groups.append({'id':f'e01-group-{len(groups)+1:03d}','role':role,'cue_ids':[row['id']],
            'start':row['start'],'end':row['end'],'text':cue['translation'],
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
        str(bank_path):digest(bank_path)}
    return {'project_id':100,'episode':1,'groups':groups,'inputs_sha256':inputs,
        'max_new_tts':len({g['cache_key'] for g in groups}),'new_clone_count':0,
        'native_listening_passed':False,'speaker_audio_verified':False,
        'grouping_review_required':True,'performance_parameters_are_not_verified_emotion_transfer':True}


def prepare():
    plan=build_plan();path=ROOT/'speech-plan.private.json'
    if path.exists() and read_json(path)!=plan:raise ValueError('Production inputs changed; preserve prior paid plan')
    save_json(path,plan)
    save_json(ROOT/'progress.private.json',{'stage':'speech_plan_ready_review_pending',
        'groups':len(plan['groups']),'max_new_tts':plan['max_new_tts'],'new_clone_count':0})
    return plan


def generate(plan,config):
    approval=read_json(ROOT/'speech-approval.private.json')
    if (approval['plan_sha256']!=digest(ROOT/'speech-plan.private.json')
        or approval['max_new_tts']!=plan['max_new_tts'] or approval['new_clones']!=0
        or approval['speech_groups_approved'] is not True
        or digest(approval['audit_report_path'])!=approval['audit_report_sha256']):
        raise ValueError('Actual finite speech plan review required')
    if plan!=build_plan():raise ValueError('Current source or voice bank differs')
    # Check every unknown submission before starting any new paid work.
    for pending in CACHE.rglob('*.submission-pending.json'):
        if not (pending.parent/'submission.private.json').exists():
            raise ValueError('Unknown earlier speech submission; do not generate again')
    contexts=threading.local();completed={};lock=threading.Lock()
    def produce(group):
        request=group['request'];key=group['cache_key'];folder=CACHE/key;folder.mkdir(parents=True,exist_ok=True)
        with process_lock(folder/'cache.lock'):
            marker=folder/'request.private.json'
            if marker.exists():
                saved=read_json(marker)
                if saved['key']!=key or request_key(saved['request'])!=key:raise ValueError('Cached request changed')
                request=saved['request']
            else:save_json(marker,{'key':key,'request':request})
            wav=folder/'raw.wav';receipt=folder/'raw-receipt.private.json'
            if wav.exists() or receipt.exists():
                r=read_json(receipt)
                if r['key']!=key or digest(wav)!=r['sha256']:raise ValueError('Existing paid WAV changed')
            else:
                if not hasattr(contexts,'client'):
                    from mflix_client import Mflix
                    contexts.client=Mflix(config)
                client=contexts.client
                submitted=safe_submit(client,'generateAudio',{'request':request},folder/'submission.private.json')
                task=submitted.get('taskId') if isinstance(submitted,dict) else None
                if type(task) is not int:raise ValueError('Unknown speech submission result; preserve receipt')
                status_path=folder/'task.private.json';status=read_json(status_path) if status_path.exists() else {}
                deadline=time.monotonic()+900
                while status.get('taskStatus') not in (2,3):
                    if time.monotonic()>deadline:raise ValueError('Known speech task still pending; poll same task, never resubmit')
                    status=client.task(task);save_json(status_path,status)
                    if status.get('taskStatus') not in (2,3):time.sleep(10)
                if status['taskStatus']!=2:raise ValueError('Speech task failed; no automatic new attempt')
                url=status.get('resultAudioUrl') or (status.get('resultAudioUrls') or [None])[0]
                if not isinstance(url,str) or urlsplit(url).scheme!='https':raise ValueError('No HTTPS generated audio')
                part=folder/'raw.download.part';size=0
                with client.http.get(url,stream=True,timeout=120) as response,part.open('wb') as stream:
                    response.raise_for_status()
                    for chunk in response.iter_content(1024*1024):
                        size+=len(chunk)
                        if size>32*1024*1024:raise ValueError('Generated audio exceeds bound')
                        stream.write(chunk)
                part.replace(wav);save_json(receipt,{'key':key,'task_id':task,'sha256':digest(wav)})
            value={'group_id':group['id'],'key':key,'raw_path':str(wav),'raw_sha256':digest(wav)}
        with lock:
            completed[group['id']]=value
            save_json(ROOT/'progress.private.json',{'stage':'generating_grouped_speech','completed':len(completed),
                'total':len(plan['groups']),'max_new_tts':plan['max_new_tts'],'new_clone_count':0})
        return value
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(produce,plan['groups']))
    save_json(ROOT/'generation-result.private.json',{'plan_sha256':digest(ROOT/'speech-plan.private.json'),
        'groups':results,'new_clone_count':0,'native_listening_passed':False})
    save_json(ROOT/'progress.private.json',{'stage':'grouped_speech_ready_fit_pending','completed':len(results),
        'total':len(results),'new_clone_count':0})


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


if __name__=='__main__':main()
