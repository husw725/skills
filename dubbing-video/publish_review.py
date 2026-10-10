"""Register final dubbing deliverables in an existing Review project on Windows."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZipInfo

from dub_episode import digest
from mflix_client import Mflix
from process_lock import process_lock
from translate import fingerprint, read_json, save_json


def document(path, paragraphs):
    """Small deterministic DOCX; no new package dependency or stale script content."""
    text=''.join('<w:p><w:r><w:t xml:space="preserve">'+escape(str(p))+'</w:t></w:r></w:p>' for p in paragraphs)
    parts={
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+text+'<w:sectPr/></w:body></w:document>'}
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,'w') as z:
        for name,body in parts.items():z.writestr(ZipInfo(name,date_time=(1980,1,1,0,0,0)),body.encode('utf-8'))
    with ZipFile(path) as z:
        from xml.etree.ElementTree import fromstring
        if z.testzip():raise ValueError('Invalid DOCX archive')
        for name in parts:fromstring(z.read(name))


def materials(client, project_id):
    d=client.call('getProjectReviewMaterials',{'projectId':project_id,'isNeedArtDirectionSubMaterials':False})
    return [r for key in ('documentMaterials','artDirectionMaterials','finalCutMaterials') for r in d.get(key,[])]


def check_matches(rows, spec):
    matches=[r for r in rows if r.get('gateType')==spec['gateType'] and r.get('name')==spec['name']]
    if len(matches)>1:raise ValueError('Duplicate target material names; inspect before registration')
    if matches:
        row=matches[0]
        if row.get('url')!=spec['url']:raise ValueError('Existing material points to a different version; no overwrite')
        if spec['gateType']=='FINAL_CUT' and not set(spec['tags']).issubset(set(row.get('tags') or [])):
            raise ValueError('Existing video missing required film tag; inspect before registration')
        if row.get('projectId')!=spec['projectId']:raise ValueError('Returned material belongs to another project')
        return row


def register(client, spec, ledger, path):
    identity=spec['gateType']+'|'+spec['name'];signature=fingerprint(spec)
    old=ledger['items'].get(identity,{})
    if old and old.get('fingerprint')!=signature:raise ValueError('Registration input changed; existing receipt preserved')
    row=check_matches(materials(client,spec['projectId']),spec)
    if row:
        ledger['items'][identity]={'fingerprint':signature,'status':'verified','asset_id':row['assetId'],'material':spec,'verified_at':time.time()}
        save_json(path,ledger)
        return row['assetId']
    if old.get('status') in ('submitting','awaiting_readback','verified'):
        raise ValueError('Prior submission not found; outcome uncertain, automatic duplicate create blocked')
    ledger['items'][identity]={'fingerprint':signature,'status':'submitting','material':spec,'started_at':time.time()}
    save_json(path,ledger)
    # Never retry a create after a timeout. Reconcile through a read on the next run.
    result=client.call('createReviewMaterial',{'material':spec})
    ledger['items'][identity].update(status='awaiting_readback',response=result)
    save_json(path,ledger)
    row=None
    for _ in range(3):
        row=check_matches(materials(client,spec['projectId']),spec)
        if row:break
    if not row:raise ValueError('New material not visible; receipt retained, no duplicate retry')
    ledger['items'][identity].update(status='verified',asset_id=row['assetId'],verified_at=time.time())
    save_json(path,ledger)
    return row['assetId']


def inventory(project, film, source_project_id, project_id, folder):
    state=read_json(project/'output/dashboard/publication-state.json')
    if len(state['videos'])!=32 or len(state.get('subtitles',{}))!=32:raise ValueError('Expected 32 verified final videos and subtitles')
    specs=[];dialogue=[film+' — Português (Brasil): roteiro de dublagem',
        'Texto efetivamente usado na dublagem; janelas de produção, não alinhamento palavra a palavra.'];notes=[]
    base='https://starlitshorts.s3.amazonaws.com/'
    for number in range(1,33):
        video=state['videos'][str(number)];subtitle=state['subtitles'][str(number)]
        candidates=list((project/f'output/drama-01/episode-{number:02d}').glob('dub-*/render-report.json'))
        report=read_json(max(candidates,key=lambda p:p.stat().st_mtime))
        if report.get('status')!='rendered_draft' or not report.get('video_payload_identical') or report['output_sha256']!=video['sha256'] or subtitle['video_sha256']!=video['sha256']:
            raise ValueError('Unverified final video/subtitle version')
        video_path=Path(report['output'])
        if not video_path.is_absolute():video_path=project/video_path
        if digest(video_path)!=video['sha256']:raise ValueError('Local video differs from published version')
        subtitle_path=project/f'output/dashboard/subtitles/{film}_EP{number:02d}_pt-BR.srt'
        if digest(subtitle_path)!=subtitle['sha256']:raise ValueError('Local final subtitle changed')
        note=f'Source film: {film}; original Review project: {source_project_id}; episode: {number:02d}; language: pt-BR. Native pronunciation, voice and performance review pending.'
        duration=float(report['duration_seconds'])
        if not math.isfinite(duration):raise ValueError('Invalid duration')
        specs.append({'projectId':project_id,'gateType':'FINAL_CUT','name':f'{film} | EP.{number:02d} | pt-BR',
            'url':base+video['key'],'tags':[film,'pt-BR'],'durationSeconds':round(duration),'note':note+' Video SHA256: '+video['sha256']})
        specs.append({'projectId':project_id,'gateType':'DOCUMENT','documentKind':'DOCUMENT','name':f'{film} | EP.{number:02d} | pt-BR subtitles.srt',
            'url':base+subtitle['key'],'note':note+' Final subtitle SHA256: '+subtitle['sha256']+'; bound video SHA256: '+video['sha256']})
        dialogue.extend(['',f'EP.{number:02d}'])
        for row in report['utterances']:
            dialogue.append(f"[{row['start']:.3f}–{row['end']:.3f}] {row['voice']}: {row['translation']}")
        notes.append(f"EP.{number:02d}: {duration:.3f}s; video SHA256 {video['sha256']}; subtitle SHA256 {subtitle['sha256']}; timing-review units {report.get('timing_quality_review_count',0)}")
    docs=[(f'{film}_pt-BR_Dubbing_Dialogue.docx','SCRIPT',dialogue),
        (f'{film}_pt-BR_Delivery_Notes.docx','DOCUMENT',[film+' — pt-BR delivery notes',
            f'English source Review project: {source_project_id}. Target Review project: {project_id}. 32 episodes.',
            'Original picture retained; Brazilian Portuguese dubbing with original BGM/SFX. No subtitle burn-in.',
            'Subtitle dialogue and production windows exported from actual rendered utterances. Not word-level alignment.',
            'Native pt-BR listening, pronunciation and performance approval pending. Timing fitting warnings retained.',
            'The older Review screenplay differs from the final cut; user-supplied final.html was the supplementary storyboard reference for this film only.',
            'Reference SHA256: 6efd76bfd6d0227e0d8a00dea6ca0d3e4132d87d0042e91aa39f56128ad0bb38.',
            'Names: Laura; Carmilla is the internal character ID, localized dialogue name Camila; Irina; Elisabeth → Elisabete; historical name Mircalla retained.',
            'Existing delivery page: '+base+'aigc/drama/dubbing-video/carmilla-20261009/index.html',
            'Unresolved source/listening notes: EP29 How many years may be an ASR error (storyboard: Her minions); source text preserved pending source listening. EP32 two mixed-speaker cues split at source acoustic pauses; exact speech boundaries pending listening.',*notes])]
    for filename,kind,paragraphs in docs:
        path=folder/filename;document(path,paragraphs)
        specs.append({'projectId':project_id,'gateType':'DOCUMENT','documentKind':kind,'name':filename,'local_file':str(path),
            'note':f'{film}; pt-BR; source Review project {source_project_id}; actual final dubbing records; native listening review pending.'})
    return specs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True,type=Path);p.add_argument('--project-id',required=True,type=int)
    p.add_argument('--project-name',required=True);p.add_argument('--film',required=True,choices=['Carmilla'])
    p.add_argument('--source-project-id',required=True,type=int);p.add_argument('--limit',type=int)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business registration runs on Windows')
    project=Path(__file__).resolve().parent;folder=project/f'output/review-publication/{args.project_id}/{args.film}'
    folder.mkdir(parents=True,exist_ok=True);path=folder/'receipts.private.json'
    with process_lock(folder/'publication.lock',timeout=0):
        ledger=read_json(path) if path.exists() else {'project_id':args.project_id,'film':args.film,'items':{},'uploads':{}}
        if ledger['project_id']!=args.project_id or ledger['film']!=args.film:raise ValueError('Registration scope changed')
        client=Mflix(args.config)
        projects=client.call('getProjects',{'pageNum':1,'pageSize':100})
        target=[r for r in projects if r['id']==args.project_id and r['name']==args.project_name]
        if len(target)!=1:raise ValueError('Explicit target project identity not found')
        specs=inventory(project,args.film,args.source_project_id,args.project_id,folder)
        save_json(folder/'inventory.private.json',specs)
        for index,spec in enumerate(specs[:args.limit] if args.limit else specs,1):
            spec=dict(spec)
            if 'local_file' in spec:
                local=Path(spec.pop('local_file'));sha=digest(local);cached=ledger.setdefault('uploads',{}).get(sha)
                if not cached:
                    cached={'url':client.upload(local),'sha256':sha};ledger['uploads'][sha]=cached;save_json(path,ledger)
                spec['url']=cached['url'];spec['note']+=' SHA256: '+sha
            asset_id=register(client,spec,ledger,path)
            print('VERIFIED',index,spec['gateType'],spec['name'],'asset',asset_id,flush=True)
        rows=materials(client,args.project_id)
        for item in ledger['items'].values():
            if item['status']=='verified':
                remote=check_matches(rows,item['material'])
                if not remote or remote['assetId']!=item['asset_id']:raise ValueError('Final readback differs from receipt')
        save_json(folder/'progress.json',{'verified':len([i for i in ledger['items'].values() if i['status']=='verified']),
            'total':len(specs),'stage':'pilot_complete' if args.limit else 'complete','updated_at':time.time()})
        print('REVIEW_REGISTRATION_COMPLETE',args.project_id,len(ledger['items']),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as e:
        print('REVIEW_REGISTRATION_STOPPED',type(e).__name__,flush=True)
        raise SystemExit(1)
