"""Receive the authorized 32-episode subtitle/audio share; no paid generation."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import collections
import json
import re
import subprocess
import sys
import time
from translate import read_json,save_json,fingerprint
from dub_episode import digest
from cartesia_pilot import bind
from process_lock import process_lock
from prepare_drama_assets import download

ROOT=Path('output/four-dramas-20261030')
OUT=Path('output/review-project-100/netdisk-source-preparation')
SOURCE=Path('input/review-project-100/netdisk')
FFMPEG=Path(r'D:\Program Files\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe')


def scope(item):
    if (not re.fullmatch(r'[1-9][0-9]*',str(item['fs_id']))
      or type(item['size']) is not int or not 0<item['size']<=2*1024**3):
        raise ValueError('Positive source identity and bounded source length required')
    name=item['server_filename']
    reserved={'CON','PRN','AUX','NUL'}|{f'{p}{n}' for p in ('COM','LPT') for n in range(1,10)}
    if (not name or Path(name).name!=name or '/' in name or '\\' in name
      or any(c in name for c in '<>:"|?*') or any(ord(c)<32 for c in name)
      or name.endswith((' ','.')) or name.split('.')[0].rstrip(' .').upper() in reserved):
        raise ValueError('Unsafe original filename')
    match=re.search(r'(?i)EP\D*(\d+)',name)
    if not match or not 1<=int(match[1])<=32:raise ValueError('Outside supplied episode range')
    parent=item['path'].rsplit('/',1)[0]
    if name.lower().endswith('.srt'):kind='subtitle'
    elif parent.endswith('_dialog'):kind='dialog'
    elif parent.endswith('_SFX'):kind='sfx'
    elif parent.endswith('_\u5b8c\u6574\u97f3\u9891'):kind='fullmix'
    else:raise ValueError('Unknown source track type')
    return int(match[1]),kind


def receive(item,url):
    ep,kind=scope(item);dest=SOURCE/kind/item['server_filename'];p=OUT/'receipts'/f'{item["fs_id"]}.private.json'
    prior=read_json(p) if p.exists() else None
    if dest.exists() and not prior:raise ValueError('Orphan source file requires reconciliation; never adopt blindly')
    if prior and prior['source_fingerprint']!=fingerprint(item):raise ValueError('Source object changed')
    part=dest.with_name(dest.name+'.download.part');marker=dest.with_name(dest.name+'.download-source.private.json')
    if part.exists() and not marker.exists():raise ValueError('Orphan partial source requires reconciliation')
    # Bind immutable inventory identity, never an expiring dlink. Do not adopt old bytes.
    bind(marker,{'source_fingerprint':fingerprint(item),'bytes':item['size'],'path':str(dest)})
    result=download({'bytes':item['size']},url,dest,receipt=prior,direct=True)
    result.update(source_fingerprint=fingerprint(item),source_fs_id=str(item['fs_id']),episode=ep,kind=kind,
      original_filename=item['server_filename'],source_md5_as_reported=item.get('md5'),source_md5_independently_verified=False)
    save_json(p,result)
    return result


def import_subtitles(assets):
    """One import with source-bound staging; ambiguous partial outputs are preserved."""
    rows=[r for r in assets.values() if r['kind']=='subtitle']
    if len(rows)!=32 or {r['episode'] for r in rows}!=set(range(1,33)):
        raise ValueError('Exactly one verified subtitle per episode is required')
    sources={}
    for r in rows:
        p=Path(r['path'])
        if p.parent!=SOURCE/'subtitle' or digest(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:
            raise ValueError('Subtitle source changed')
        sources[str(r['episode'])]={'file':p.name,'sha256':r['sha256'],'fs_id':r['source_fs_id']}
    if {p.name for p in (SOURCE/'subtitle').glob('*') if p.suffix.lower()=='.srt'}!={r['file'] for r in sources.values()}:
        raise ValueError('Unrequested subtitle source file exists')
    key=fingerprint(sources);ledger_path=OUT/'subtitle-import.private.json'
    stage=Path('output/review-project-100/subtitles-staging')
    target=Path('output/review-project-100/subtitles')
    old=read_json(ledger_path) if ledger_path.exists() else None
    if old and old['source_fingerprint']!=key:raise ValueError('Subtitle import source changed')
    def artifacts(folder):return {str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file()}
    def verify(folder):
        if not old or old.get('status') not in ('prepared','complete') or artifacts(folder)!=old['artifact_sha256']:
            raise ValueError('Unknown or partial subtitle import preserved for reconciliation')
    if target.exists():
        verify(target)
        if stage.exists():raise ValueError('Ambiguous staging and final subtitles both exist')
    elif stage.exists():
        verify(stage);stage.rename(target)
    else:
        if old:raise ValueError('Previously started subtitle import is incomplete; reconcile before retry')
        old={'source_fingerprint':key,'sources':sources,'status':'staging'};save_json(ledger_path,old)
        stage.mkdir(parents=True)
        subprocess.run([sys.executable,'prepare_subtitles.py',str(SOURCE/'subtitle'),'--output-dir',str(stage)],check=True)
        manifest=read_json(stage/'subtitle-manifest.json')
        imported={str(r['episode']):{'file':r['source_file'],'sha256':r['source_sha256']} for r in manifest['episodes']}
        if imported!={ep:{'file':r['file'],'sha256':r['sha256']} for ep,r in sources.items()} or len(manifest['episodes'])!=32:
            raise ValueError('Imported subtitle identity or SHA differs')
        required={'subtitle-manifest.json','dialogue.en.json','series-source.txt'}|{f'normalized/episode-{n:02}.en.srt' for n in range(1,33)}
        outputs=artifacts(stage)
        if set(outputs)!=required:raise ValueError('Subtitle import output coverage differs')
        old.update(status='prepared',artifact_sha256=outputs);save_json(ledger_path,old)
        stage.rename(target)
    old['status']='complete';save_json(ledger_path,old)
    return digest(target/'subtitle-manifest.json')


def main():
    if sys.platform!='win32':raise ValueError('Run source files on Windows')
    OUT.mkdir(parents=True,exist_ok=True)
    with process_lock(OUT/'preparation.lock',timeout=0):
        inv=read_json(ROOT/'monte-netdisk-inventory.private.json');links=read_json(ROOT/'monte-netdisk-links.private.json')
        files=inv['files'];counts=collections.Counter(scope(x)[1] for x in files)
        if (str(inv['shareid'])!='36598724241' or str(inv['share_uk'])!='1100102321809' or len(files)!=130
          or counts!={'subtitle':32,'dialog':32,'sfx':34,'fullmix':32}
          or len({str(x['fs_id']) for x in files})!=130):raise ValueError('Outside exact user share scope')
        paths=[str(SOURCE/scope(x)[1]/x['server_filename']).casefold() for x in files]
        if len(set(paths))!=130:raise ValueError('Windows destination collision')
        if links['errno']!=0:raise ValueError('Authorized links unavailable')
        by_id={str(x['fs_id']):x['dlink'] for x in links['list']}
        if len(links['list'])!=130 or len(by_id)!=130 or set(by_id)!={str(x['fs_id']) for x in files}:raise ValueError('Missing, duplicate or unrequested links')
        bind(OUT/'inventory-fingerprint.json',inv)
        path=OUT/'progress.private.json';state=read_json(path) if path.exists() else {'inventory_fingerprint':fingerprint(inv),'assets':{},'audio_probes':{},'errors':{}}
        if state['inventory_fingerprint']!=fingerprint(inv):raise ValueError('Share inventory changed')
        state.update(stage='downloading_source_subtitles_and_audio',total=130,new_clone_count=0,paid_generation_started=False)
        def persist():state.update(downloaded=len(state['assets']),updated_at=time.time());save_json(path,state)
        persist();jobs={};subtitle_import_attempted=False
        ordered=sorted(files,key=lambda x:(0 if scope(x)[1]=='subtitle' else 1 if scope(x)[0]==1 else 2,scope(x)[0],scope(x)[1],x['server_filename']))
        with ThreadPoolExecutor(max_workers=4) as pool:
            for item in ordered:jobs[pool.submit(receive,item,by_id[str(item['fs_id'])])]=item
            for future in as_completed(jobs):
                item=jobs[future];key=str(item['fs_id'])
                try:
                    r=future.result();state['assets'][key]=r;state['errors'].pop(key,None)
                    if r['kind']!='subtitle':
                        result=subprocess.run([str(FFMPEG.with_name('ffprobe.exe')),'-v','error','-show_format','-show_streams','-of','json',r['path']],check=True,capture_output=True)
                        probe=json.loads(result.stdout)
                        if not any(s['codec_type']=='audio' for s in probe['streams']):raise ValueError('Source lacks audio')
                        record=OUT/'audio-probes'/f'{key}.private.json';save_json(record,{'source_sha256':r['sha256'],'probe':probe,'dialogue_purity_verified':False,'timeline_verified':False});state['audio_probes'][key]=str(record)
                    persist();print('NETDISK_SOURCE_READY',r['episode'],r['kind'],len(state['assets']),130,flush=True)
                    subtitles=[x for x in state['assets'].values() if x['kind']=='subtitle']
                    if len(subtitles)==32 and not subtitle_import_attempted:
                        subtitle_import_attempted=True;state['subtitle_import_attempted']=True;persist()
                        try:
                            imported_sha=import_subtitles(state['assets'])
                            state.update(subtitles_imported=True,subtitle_manifest_sha256=imported_sha)
                            state['errors'].pop('subtitle_import',None);state.pop('subtitle_import_error',None)
                        except Exception as exc:
                            state['subtitles_imported']=False;state.pop('subtitle_manifest_sha256',None)
                            state['subtitle_import_error']=type(exc).__name__;state['errors']['subtitle_import']={'error_type':type(exc).__name__}
                        persist()
                except Exception as exc:
                    state['errors'][key]={'error_type':type(exc).__name__};persist();print('SOURCE_NEEDS_REVIEW',key,type(exc).__name__,flush=True)
        state.update(stage='sources_received_version_alignment_pending' if not state['errors'] else 'source_download_partial_needs_review',finished_at=time.time(),
          source_track_labels_not_listening_verified=True,screenplay_context_reviewed=False,formal_translation_ready=False)
        persist()
        if state['errors']:raise SystemExit(2)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True);sys.stdout=(OUT/'download.log').open('a',encoding='utf-8',buffering=1);sys.stderr=sys.stdout
    try:main()
    except Exception as exc:
        path=OUT/'progress.private.json';state=read_json(path) if path.exists() else {}
        save_json(path,{**state,'stage':'failed_needs_review','error_type':type(exc).__name__,'updated_at':time.time()});raise
