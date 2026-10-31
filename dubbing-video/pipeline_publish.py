"""Publish one technically approved episode and matching SRT, preserving existing Review assets."""
import argparse
import hashlib
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, urlunsplit, unquote
import posixpath

from dub_episode import digest, probe
from process_lock import process_lock
from publish_review import ReviewClient, materials, register
from translate import read_json, save_json, fingerprint

FILMS={96:"Perfect Housewife's Deadly Secret",110:'Seduced by the Dark Lord I Swore To Kill',
       102:'They Bullied the Wrong Heiress',100:'The Count of Monte Cristo'}


def verify_object(client,url,path):
    expected=path.stat().st_size;total=0;sha=hashlib.sha256()
    try:
        with client.http.get(url,stream=True,timeout=180,allow_redirects=False,headers={'Accept-Encoding':'identity'}) as response:
            if response.status_code!=200:raise ValueError('Remote object unavailable')
            for block in response.iter_content(1024*1024):
                total+=len(block)
                if total>expected:raise ValueError('Remote size exceeds local')
                sha.update(block)
    except Exception:raise RuntimeError('Uploaded object readback failed; URL omitted') from None
    if total!=expected or sha.hexdigest()!=digest(path):raise ValueError('Uploaded object SHA or size differs')


def object_key(url):
    parsed=urlsplit(url)
    path=unquote(parsed.path)
    host=(parsed.hostname or '').lower()
    if host.endswith('.amazonaws.com') and (host.startswith('s3.') or host.startswith('s3-')):
        path='/' + path.lstrip('/').partition('/')[2]  # path-style bucket/key
    # Compare key paths across CDN/S3 host aliases conservatively, ignoring signed queries.
    return posixpath.normpath('/'+path.lstrip('/'))


def upload(client,path,ledger,receipt,protected_keys=frozenset()):
    sha=digest(path);item=ledger['uploads'].get(sha)
    if item is None:
        ledger['uploads'][sha]={'status':'preparing_url','sha256':sha,'bytes':path.stat().st_size};save_json(receipt,ledger)
        signed=client.call('createFilePresignedUrl',{'originalFileName':path.name})
        u=urlsplit(signed) if isinstance(signed,str) else None
        if u is None or u.scheme!='https' or not u.hostname or u.username or u.password:
            raise ValueError('Expected credential-free HTTPS upload endpoint')
        item={'status':'upload_pending','sha256':sha,'bytes':path.stat().st_size,'signed_url':signed,
              'url':urlunsplit((u.scheme,u.netloc,u.path,'',''))}
        ledger['uploads'][sha]=item;save_json(receipt,ledger)
    if item['sha256']!=sha or item['bytes']!=path.stat().st_size or 'url' not in item:
        raise ValueError('Upload reservation uncertain or source changed; do not allocate another object')
    if item['status']!='verified':
        if object_key(item['url']) in protected_keys:
            raise ValueError('Upload object collides with an existing Review asset; no PUT issued')
        # Repeating a PUT of the same bytes to the same object is safe; never allocate a new key here.
        try:
            with path.open('rb') as stream:
                response=client.http.put(item['signed_url'],data=stream,timeout=300,allow_redirects=False)
            if response.status_code not in (200,201,204):raise ValueError('Upload rejected')
        except Exception:raise RuntimeError('Upload incomplete or uncertain; original object reservation retained') from None
    verify_object(client,item['url'],path)
    item.update(status='verified',verified_at=time.time());save_json(receipt,ledger)
    return item['url']


def protected(rows):
    keys=('assetId','projectId','gateType','name','url','version','parentAssetId','tags')
    return {str(row['assetId']):{k:row.get(k) for k in keys} for row in rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=int,choices=tuple(FILMS),required=True)
    parser.add_argument('--episode',type=int,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--approval',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--ffmpeg',type=Path,required=True)
    parser.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Business publishing runs on Windows')
    root=Path(f'output/review-project-{args.project}/episode-{args.episode:02d}/pipeline-publication-20261031')
    root.mkdir(parents=True,exist_ok=True)
    with process_lock(root/'publication.lock',timeout=0):
        report=read_json(args.report);approval=read_json(args.approval)
        video=Path(report['output']);subtitle=Path(report['subtitle'])
        plan_path=args.report.parent/'speech-plan.private.json';plan=read_json(plan_path)
        if (plan['project_id']!=args.project or plan['episode']!=args.episode
            or report['plan_sha256']!=digest(plan_path) or approval['project_id']!=args.project
            or approval['episode']!=args.episode):raise ValueError('Episode publication identity differs')
        if (not report.get('picture_payload_identical') or approval['technical_media_approved'] is not True
            or approval['render_report_sha256']!=digest(args.report)
            or approval['video_sha256']!=report['output_sha256'] or digest(video)!=report['output_sha256']
            or approval['subtitle_sha256']!=report['subtitle_sha256'] or digest(subtitle)!=report['subtitle_sha256']
            or digest(approval['audit_report_path'])!=approval['audit_report_sha256']):
            raise ValueError('Actual approved video, subtitle, or audit changed')
        film=FILMS[args.project];version=report['output_sha256'][:12]
        duration=float(probe(video,args.ffmpeg)['format']['duration'])
        scope={'project':args.project,'episode':args.episode,'target_project':148,'film':film,
               'render_sha256':digest(args.report),'approval_sha256':digest(args.approval)}
        receipt=root/'receipts.private.json'
        ledger=read_json(receipt) if receipt.exists() else {'scope':scope,'uploads':{},'items':{}}
        if ledger['scope']!=scope:raise ValueError('Publication source changed; preserve receipts')
        if not args.publish:
            save_json(root/'preflight.private.json',{'scope':scope,'duration':duration,'ready_to_publish':True})
            print('PUBLICATION_PREFLIGHT_READY',args.project,args.episode);return
        client=ReviewClient(args.config,root/'service-error.private.json')
        projects=client.call('getProjects',{'pageNum':1,'pageSize':100})
        if len([p for p in projects if p['id']==148 and p['name']=='PT Transalte'])!=1:
            raise ValueError('Expected PT target project identity not found')
        old_target=protected(materials(client,148));old_source=protected(materials(client,args.project))
        note=(f'{film}; EP{args.episode:02d}; pt-BR candidate; native pronunciation and performance listening pending. '
              f'Picture retained. Background timeline/purity requires listening. Video SHA256 {report["output_sha256"]}; '
              f'matching SRT SHA256 {report["subtitle_sha256"]}.')
        old_keys={object_key(row['url']) for row in [*old_target.values(),*old_source.values()] if isinstance(row.get('url'),str) and row['url'].startswith('https://')}
        video_url=upload(client,video,ledger,receipt,old_keys)
        subtitle_url=upload(client,subtitle,ledger,receipt,old_keys)
        base=f'{film} | EP{args.episode:02d} | pt-BR | {version}'
        specs=[{'projectId':148,'gateType':'FINAL_CUT','name':base,'url':video_url,'durationSeconds':round(duration),
                'tags':[film,'pt-BR','candidate',version],'note':note},
               {'projectId':148,'gateType':'DOCUMENT','documentKind':'DOCUMENT','name':base+' | subtitles.srt',
                'url':subtitle_url,'note':note}]
        ids=[register(client,spec,ledger,receipt) for spec in specs]
        after=protected(materials(client,148))
        if any(after.get(key)!=row for key,row in old_target.items()) or protected(materials(client,args.project))!=old_source:
            raise ValueError('Existing Review assets changed; inspect without overwriting')
        save_json(root/'progress.private.json',{'stage':'review_candidate_delivered','video_asset_id':ids[0],
                  'subtitle_asset_id':ids[1],'video_sha256':report['output_sha256'],
                  'subtitle_sha256':report['subtitle_sha256'],'native_listening_passed':False,'updated_at':time.time()})
        print('REVIEW_CANDIDATE_DELIVERED',args.project,args.episode,ids)


if __name__=='__main__':main()
