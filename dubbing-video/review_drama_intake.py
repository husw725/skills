"""Download immutable Review references and inspect documents/media on Windows.

This stage never calls a generative, cloning, upload or Review mutation API.
Dialogue and source URLs are supplied only through an ignored private manifest.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import zipfile
import requests
from cartesia_pilot import bind
from process_lock import process_lock
from translate import read_json,save_json,fingerprint
from dub_episode import digest


AUTHORIZED_PROJECTS={96,110,102,100}
AUTHORIZED_MANIFEST_FINGERPRINT='cb592e57cbfdcc90b742a8a8004d08d4f5e56820d89a2e4b561d5ef039432a2a'


def validate_manifest(m):
    projects=m['project_ids'];items=m['items']
    if (len(projects)!=4 or any(type(n) is not int for n in projects)
      or set(projects)!=AUTHORIZED_PROJECTS or len(items)!=176
      or sum(x['kind']=='video' for x in items)!=168
      or sum(x['kind']=='document' for x in items)!=8
      or fingerprint(m)!=AUTHORIZED_MANIFEST_FINGERPRINT):
        raise ValueError('Only the exact authorized four-drama source snapshot is allowed')
    identities=[(x['project_id'],x['kind'],x['asset_id'],x['version']) for x in items]
    if len(set(identities))!=len(items):raise ValueError('Duplicate source work')
    for item in items:
        if item['project_id'] not in AUTHORIZED_PROJECTS:raise ValueError('Unexpected project')
        validate_item(item)


def validate_item(item):
    if type(item['project_id']) is not int or item['project_id']<=0:raise ValueError('Invalid project')
    if type(item['asset_id']) is not int or item['asset_id']<=0:raise ValueError('Invalid source asset')
    if type(item['version']) is not int or item['version']<=0:raise ValueError('Invalid version')
    u=urllib.parse.urlsplit(item['url'])
    if (u.scheme!='https' or u.hostname!='static.starlitshorts.com' or u.username or u.password
      or u.port not in (None,443) or u.fragment):raise ValueError('Unexpected source download host')
    ext=Path(u.path).suffix.lower()
    allowed={'.pdf','.docx','.txt'} if item['kind']=='document' else {'.mp4','.mov'} if item['kind']=='video' else set()
    if ext not in allowed:raise ValueError('Unexpected source extension')
    return ext


def download(item):
    ext=validate_item(item)
    folder=Path('input')/f'review-project-{item["project_id"]}'/('screenplay' if item['kind']=='document' else 'reference-video')
    folder.mkdir(parents=True,exist_ok=True)
    dest=folder/f'asset-{item["asset_id"]}-v{item["version"]}{ext}'
    receipt=dest.with_name(dest.name+'.receipt.private.json');key=fingerprint(item)
    if dest.exists():
        if not receipt.exists():raise ValueError('Existing source lacks verified receipt; preserve and reconcile')
        r=read_json(receipt)
        if r['source_fingerprint']!=key or r['bytes']!=dest.stat().st_size or r['sha256']!=digest(dest):
            raise ValueError('Existing source changed; never overwrite')
        return r
    session=requests.Session();session.trust_env=False
    with session.head(item['url'],headers={'Accept-Encoding':'identity'},timeout=(15,30),allow_redirects=False) as head:
        head.raise_for_status()
        if head.status_code!=200:raise ValueError('Unexpected HEAD/redirect')
        expected=int(head.headers.get('Content-Length','0'));etag=head.headers.get('ETag')
        if not 0<expected<=2*1024**3 or not etag or etag.startswith('W/'):
            raise ValueError('Positive bounded size and strong source ETag required')
    part=dest.with_name(dest.name+'.download.part');binding=dest.with_name(dest.name+'.download-source.private.json')
    signature={'source_fingerprint':key,'etag':etag,'bytes':expected}
    if binding.exists() and read_json(binding)!=signature:raise ValueError('Server object changed; keep partial source')
    if part.exists() and not binding.exists():raise ValueError('Unbound partial source; preserve for reconciliation')
    save_json(binding,signature);failures=0
    while not part.exists() or part.stat().st_size<expected:
        offset=part.stat().st_size if part.exists() else 0
        last=min(expected-1,offset+16*1024**2-1)
        if offset>=expected:raise ValueError('Partial exceeds source object')
        try:
            with session.get(item['url'],headers={'Range':f'bytes={offset}-{last}','If-Range':etag,'Accept-Encoding':'identity'},
              stream=True,timeout=(15,90),allow_redirects=False) as response:
                response.raise_for_status()
                if response.headers.get('ETag')!=etag:raise ValueError('Source ETag changed during transfer')
                if response.status_code==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match or tuple(map(int,match.groups()))!=(offset,last,expected):raise ValueError('Incorrect resumed byte range')
                    end=last+1
                elif response.status_code==200 and offset==0:end=expected
                else:raise ValueError('Ignored resume range or redirect; do not append')
                with part.open('ab' if offset else 'wb') as stream:
                    for chunk in response.iter_content(1024**2):
                        if chunk:
                            if stream.tell()+len(chunk)>end:raise ValueError('Response exceeds authorized source range')
                            stream.write(chunk)
                if part.stat().st_size!=end:raise ValueError('Range body length mismatch')
            failures=0
        except requests.RequestException:
            failures+=1
            if failures>=3:raise RuntimeError('Read-only download failed; bound partial retained') from None
            time.sleep(2**failures)
    if part.stat().st_size!=expected:raise ValueError('Source size mismatch')
    sha=digest(part);part.replace(dest)
    result={'source_fingerprint':key,'path':str(dest),'bytes':expected,'sha256':sha,'etag':etag,
      'project_id':item['project_id'],'asset_id':item['asset_id'],'version':item['version'],
      'name':item['name'],'kind':item['kind'],'episode':item.get('episode'),'variant':item.get('variant'),
      'received_size_verified':True,'original_independent_sha256_available':False}
    save_json(receipt,result);session.close();return result


def inspect(item,receipt,ffmpeg):
    path=Path(receipt['path']);root=Path('output')/f'review-project-{item["project_id"]}'/'source-preparation'
    root.mkdir(parents=True,exist_ok=True);record_path=root/f'asset-{item["asset_id"]}-v{item["version"]}.private.json'
    if record_path.exists():
        record=read_json(record_path)
        if record['source_sha256']!=receipt['sha256']:raise ValueError('Inspection source changed')
        for p,sha in record['derived_sha256'].items():
            if digest(p)!=sha:raise ValueError('Derived inspection changed')
        return record
    derived=[];details={}
    if item['kind']=='document':
        if path.suffix=='.docx':
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(path) as archive:
                # Inspect the declared size before decompression; ignore unrelated embedded files.
                limit=20*1024**2;info=archive.getinfo('word/document.xml')
                if info.file_size>limit:raise ValueError('Document XML exceeds preparation bound')
                with archive.open(info) as member:xml=member.read(limit+1)
                if len(xml)>limit:raise ValueError('Document XML exceeds preparation bound')
            doc=ET.fromstring(xml);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text='\n'.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in doc.findall('.//w:p',ns))
        elif path.suffix=='.pdf':
            from pypdf import PdfReader
            with path.open('rb') as stream:
                doc=PdfReader(stream);details['pages']=len(doc.pages)
                text='\n\n'.join(page.extract_text() or '' for page in doc.pages)
        else:text=path.read_text(encoding='utf-8-sig')
        text_path=root/f'asset-{item["asset_id"]}-v{item["version"]}.txt';text_path.write_text(text,encoding='utf-8');derived.append(text_path)
        details.update(characters=len(text),episode_heading_candidates=re.findall(r'(?im)^\s*(?:EPISODE|EP)[ ._-]*(\d+)[^\n]*',text),
          script_classification=item.get('script_classification','candidate'),screenplay_match_reviewed=False)
    else:
        ffprobe=ffmpeg.with_name('ffprobe.exe')
        p=subprocess.run([str(ffprobe),'-v','error','-show_format','-show_streams','-of','json',str(path)],check=True,capture_output=True)
        details['probe']=__import__('json').loads(p.stdout);details['full_decode_verified']=False
        if not any(x['codec_type']=='video' for x in details['probe']['streams']):raise ValueError('Reference has no video')
        if item.get('episode')==1:
            still=root/f'asset-{item["asset_id"]}-frame.jpg';audio=root/f'asset-{item["asset_id"]}-source-16k.wav'
            subprocess.run([str(ffmpeg),'-v','error','-y','-ss','8','-i',str(path),'-frames:v','1','-vf','scale=360:-2',str(still)],check=True,capture_output=True)
            derived.append(still)
            if any(x['codec_type']=='audio' for x in details['probe']['streams']):
                subprocess.run([str(ffmpeg),'-v','error','-y','-i',str(path),'-map','0:a:0','-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(audio)],check=True,capture_output=True)
                derived.append(audio)
            details.update(subtitle_burn_in_verified=False,dialogue_isolated=False,timing_verified=False)
    record={'source_sha256':receipt['sha256'],'source_asset':{k:receipt[k] for k in ('project_id','asset_id','version','name','path')},
      'details':details,'derived_sha256':{str(p):digest(p) for p in derived},'formal_translation_ready':False}
    save_json(record_path,record);return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--ffmpeg',type=Path,required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    if sys.platform!='win32':p.error('Source materials are processed on Windows')
    if not 1<=a.workers<=4:p.error('Use one to four bounded read-only workers')
    root=a.manifest.parent;root.mkdir(parents=True,exist_ok=True)
    with process_lock(root/'intake.lock',timeout=0):
        m=read_json(a.manifest);validate_manifest(m);bind(root/'intake-fingerprint.json',m);items=m['items']
        projects=m['project_ids']
        state_path=root/'intake-progress.private.json'
        state=read_json(state_path) if state_path.exists() else {'manifest_fingerprint':fingerprint(m),'assets':{},'inspections':{},'errors':{}}
        if state['manifest_fingerprint']!=fingerprint(m):raise ValueError('Source batch changed; preserve prior checkpoints')
        state.update(stage='downloading_and_inspecting',total_assets=len(items),paid_generation_started=False,new_clone_count=0)
        def persist():state.update(downloaded=len(state['assets']),inspected=len(state['inspections']),updated_at=time.time());save_json(state_path,state)
        persist()
        order=sorted(items,key=lambda x:(0 if x['kind']=='document' else 1 if x.get('episode')==1 else 2,projects.index(x['project_id']),x['asset_id']))
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            jobs={pool.submit(download,x):x for x in order}
            for future in as_completed(jobs):
                item=jobs[future];key=f'{item["project_id"]}:{item["kind"]}:{item["asset_id"]}:{item["version"]}'
                try:
                    result=future.result();state['assets'][key]=result;persist()
                    state['inspections'][key]=inspect(item,result,a.ffmpeg);state['errors'].pop(key,None)
                    print('REFERENCE_READY',item['project_id'],item['asset_id'],len(state['assets']),len(items),flush=True)
                except Exception as e:
                    state['errors'][key]={'error_type':type(e).__name__};print('SOURCE_ITEM_NEEDS_REVIEW',item['project_id'],item['asset_id'],type(e).__name__,flush=True)
                persist()
        state.update(stage='references_ready_missing_production_assets' if not state['errors'] else 'references_partial_needs_review',
          missing_production_assets=['Original timed SRT and matching independent BGM/SFX not found in inspected Review data',
            'Clean-picture versions and episode/recut identity require confirmation per project'],finished_at=time.time())
        persist();print('INTAKE_FINISHED',state['stage'],state['downloaded'],state['inspected'],flush=True)
        if state['errors']:raise SystemExit(2)


if __name__=='__main__':main()
