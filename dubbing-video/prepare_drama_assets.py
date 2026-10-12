"""Download and verify an isolated drama's source assets; never translate or generate voices."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import requests
from process_lock import process_lock
from translate import read_json,save_json,fingerprint


def asset_scope(item):
    name=item['name']
    if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Unsafe source filename')
    match=re.search(r'(?i)ep0*(\d+)',name)
    if not match:raise ValueError('Missing episode ID')
    episode=int(match[1])
    folder=item['path'].rsplit('/',2)[1]
    kind={'纯字幕':'subtitle','纯BGM':'bgm','纯音效':'sfx','无字幕有BGM':'video'}.get(folder)
    if not kind or not 1<=episode<=30:raise ValueError('Unexpected source asset scope')
    return episode,kind


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def download(item,url,dest,receipt=None):
    dest.parent.mkdir(parents=True,exist_ok=True);expected=int(item['bytes'])
    if dest.exists():
        if dest.stat().st_size!=expected:raise ValueError('Existing source file size differs; preserved')
        digest=sha(dest)
        if receipt and digest!=receipt['sha256']:raise ValueError('Existing source file hash differs; preserved')
        return {'path':str(dest),'bytes':expected,'sha256':digest,'download_verified':True}
    if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('HTTPS source download required')
    part=dest.with_name(dest.name+'.download.part')
    for attempt in range(3):
        offset=part.stat().st_size if part.exists() else 0
        if offset==expected:break
        if offset>expected:raise ValueError('Partial download exceeds source size')
        headers={'User-Agent':'netdisk;P2SP;3.0.0.1','Referer':'https://pan.baidu.com/'}
        if offset:headers['Range']=f'bytes={offset}-'
        try:
            with requests.get(url,headers=headers,stream=True,timeout=(15,90)) as r:
                r.raise_for_status()
                if offset and r.status_code==206:
                    if not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid resumed range')
                    mode='ab'
                else:mode='wb'
                with part.open(mode) as f:
                    for chunk in r.iter_content(1024*1024):
                        if chunk:f.write(chunk)
            if part.stat().st_size!=expected:raise ValueError('Downloaded file size mismatch')
            break
        except requests.RequestException:
            if attempt==2:raise RuntimeError('Source download failed; partial retained, refresh source links if expired') from None
    if not part.exists() or part.stat().st_size!=expected:raise ValueError('Incomplete source download')
    digest=sha(part);part.replace(dest)
    return {'path':str(dest),'bytes':expected,'sha256':digest,'download_verified':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--links',type=Path,required=True)
    p.add_argument('--drama',required=True,choices=['drama-02']);p.add_argument('--ffmpeg',required=True,type=Path)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Source preparation runs on Windows')
    project=Path(__file__).resolve().parent;out=project/'output'/args.drama;source=project/'input'/args.drama
    out.mkdir(parents=True,exist_ok=True);state_path=out/'preparation-progress.json'
    with process_lock(out/'preparation.lock',timeout=0):
        items=[i for i in read_json(args.inventory) if not i['directory']]
        scopes=[asset_scope(i) for i in items]
        if len(items)!=120 or len(set(scopes))!=120:raise ValueError('Expected 30 episodes with four unique asset types')
        links=read_json(args.links);assert links['errno']==0
        by_id={str(x['fs_id']):x['dlink'] for x in links['list']}
        if {str(x['id']) for x in items}-set(by_id):raise ValueError('Missing authorized source links')
        signature=fingerprint(items)
        state=read_json(state_path) if state_path.exists() else {'source_fingerprint':signature,'assets':{},'media_prepared':[]}
        if state['source_fingerprint']!=signature:raise ValueError('Source inventory changed; old progress preserved')
        state.update(stage='downloading',film="Lady Chatterley's Lover",total_assets=120,translation_stage='waiting_for_elevenlabs_mcp',voice_generation_started=False)
        def persist():
            state.update(downloaded_assets=len(state['assets']),updated_at=time.time());save_json(state_path,state)
        persist()
        jobs={}
        order=sorted(items,key=lambda i:(0 if asset_scope(i)[1]=='subtitle' else asset_scope(i)[0],{'subtitle':0,'video':1,'bgm':2,'sfx':3}[asset_scope(i)[1]]))
        with ThreadPoolExecutor(max_workers=4) as pool:
            for item in order:
                episode,kind=asset_scope(item);identity=f'{episode:02d}:{kind}'
                dest=(source/'subtitles/original' if kind=='subtitle' else source/f'episode-{episode:02d}')/item['name']
                jobs[pool.submit(download,item,by_id[str(item['id'])],dest,state['assets'].get(identity))]=(identity,item)
            imported=False
            for future in as_completed(jobs):
                identity,item=jobs[future];state['assets'][identity]={**future.result(),'source_fs_id':str(item['id']),'filename':item['name']}
                persist();print('SOURCE_VERIFIED',identity,len(state['assets']),flush=True)
                if not imported and all(f'{ep:02d}:subtitle' in state['assets'] for ep in range(1,31)):
                    subprocess.run([sys.executable,'prepare_subtitles.py',str(source/'subtitles/original'),'--output-dir',str(out/'subtitles')],check=True)
                    state['subtitle_preparation_complete']=True;imported=True;persist()
        state['stage']='media_preparation';persist()
        for episode in range(1,31):
            if episode in state['media_prepared']:
                manifest=read_json(out/f'episode-{episode:02d}/media/media-manifest.json')
                if not all(v['sha256']==state['assets'][f'{episode:02d}:{k}']['sha256'] for k,v in manifest['assets'].items()):raise ValueError('Prepared media input changed')
                continue
            paths={k:state['assets'][f'{episode:02d}:{k}']['path'] for k in ('video','bgm','sfx')}
            with (out/'media-preparation.private.log').open('a',encoding='utf-8') as log:
                subprocess.run([sys.executable,'prepare_media.py','--video',paths['video'],'--bgm',paths['bgm'],'--sfx',paths['sfx'],
                    '--ffmpeg',str(args.ffmpeg),'--output-dir',str(out/f'episode-{episode:02d}/media')],stdout=log,stderr=log,check=True)
            state['media_prepared'].append(episode);persist();print('MEDIA_PREPARED',episode,flush=True)
        state['stage']='assets_ready_waiting_for_elevenlabs';persist()
        save_json(out/'translation-preparation-config.json',{'film':"Lady Chatterley's Lover",'episodes':30,'language':'pt-BR',
            'source_dialogue':str(out/'subtitles/dialogue.en.json'),'script_manifest':str(source/'screenplay/download-manifest.json'),
            'translation_enabled':False,'voice_cloning_enabled':False,'tts_enabled':False,'waiting_for':'ElevenLabs support in production MCP',
            'notes':['Original video includes BGM; extracted source audio is not verified isolated dialogue.','Screenplay version and source-speaker/emotion context must be reviewed before translation.','Use native pt-BR listening approval and existing drama-specific voices, never duplicate paid clones.']})
        print('ALL_SOURCE_PREPARATION_COMPLETE',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as e:
        print('SOURCE_PREPARATION_STOPPED',type(e).__name__,flush=True)
        raise
