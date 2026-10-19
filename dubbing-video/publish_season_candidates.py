"""Publish validated Carmilla revisions without replacing their Review histories."""
import argparse
import base64
import hashlib
from pathlib import Path
import sys
import time

from cartesia_pilot import bind
from dub_episode import digest, probe, run, safe_submit
from mflix_client import Mflix
from process_lock import process_lock
from publish_review import materials, register
from rerun_carmilla_season import validate_reviewed_plan,post_gap_seconds,NEIGHBOR_PAUSE_ROOT,RECONSTRUCTION_TIMING_ROOT,RECONCILED_ROOT
from translate import read_json, save_json
from upload_review_video_s3 import parallel_remote_digest

ROOTS = [Path('output/carmilla-season-revision-20261016'),
         Path('output/carmilla-season-revision-20261017-retry1'),
         Path('output/carmilla-season-final-20261017'),
         Path('output/carmilla-season-timing-repair-20261017'),
         Path('output/carmilla-season-timing-repair2-20261017'),
         Path('output/carmilla-season-resume-20261017'),
         Path('output/carmilla-season-source-resume-20261017'),
         Path('output/carmilla-season-finish-20261019'),
         Path('output/carmilla-season-neighbor-20261019'),
         Path('output/carmilla-season-finish-20261019-v2'),
         Path('output/carmilla-season-finish-20261019-ep12'),
         Path('output/carmilla-season-neighbor-20261019-v2'),
         Path('output/carmilla-season-neighbor-timing-20261019'),
         Path('output/carmilla-season-neighbor-pause-20261019'),
         Path('output/carmilla-season-subtitle-meaning-20261019'),
         Path('output/carmilla-season-subtitle-timing-20261019'),
         Path('output/carmilla-season-reconstruction-20261019'),
         RECONSTRUCTION_TIMING_ROOT,RECONCILED_ROOT]
PUBLICATION = Path('output/review-publication/148/Carmilla/season-revision-20261017')


def candidates():
    result={}
    for root in ROOTS:
        for n in range(1,33):
            if (root/f'episode-{n:02}'/'render-report.json').is_file():result[n]=root/f'episode-{n:02}'
    return result


def validate_candidate(n,folder,ffmpeg):
    if folder not in [root/f'episode-{n:02}' for root in ROOTS]:raise ValueError('Unexpected season folder')
    plan=read_json(folder/'plan.json');validate_reviewed_plan(folder,plan)
    report=read_json(folder/'render-report.json')
    video=folder/f'Carmilla_EP{n:02}_pt-BR_season-revision.mp4'
    subtitle=folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt'
    if (plan['episode']!=n or plan['project_id']!=59 or plan['blocking_issues']
            or report['episode']!=n or report['status']!='rendered_season_revision_candidate'
            or not report['video_payload_identical'] or report['new_clone_count']!=0
            or report['source_audio_in_output'] or Path(report['output'])!=video
            or digest(video)!=report['output_sha256']):raise ValueError('Unverified season candidate')
    if len(report['utterances'])!=len(plan['units']):raise ValueError('Rendered unit coverage changed')
    for expected,actual in zip(plan['units'],report['utterances']):
        if any(actual.get(k)!=v for k,v in expected.items()):raise ValueError('Rendered translation/casting/timing differs')
        if actual['atempo_factor']>1.2:raise ValueError('Unapproved speech speed')
        start=actual.get('audio_start',actual['start'])
        if start<max(0,actual['start']-.080001) or start>actual['start']:
            raise ValueError('Unapproved speech onset shift')
        allowance=post_gap_seconds(n,expected,folder==NEIGHBOR_PAUSE_ROOT/f'episode-{n:02}',
                                   folder==RECONSTRUCTION_TIMING_ROOT/f'episode-{n:02}')
        if start+actual['fitted_duration_seconds']>actual['end']+allowance+.001:
            raise ValueError('Unapproved speech end shift')
    for a,b in zip(report['utterances'],report['utterances'][1:]):
        if a.get('audio_start',a['start'])+a['fitted_duration_seconds']>b.get('audio_start',b['start'])+.001:
            raise ValueError('Rendered speech overlaps another unit')
    for filename,key in [('reviewed.json','reviewed_response_sha256'),('screenplay-context.json','reviewed_context_sha256'),
                         (subtitle.name,'translation_srt_sha256')]:
        if digest(folder/filename)!=plan[key]:raise ValueError('Approved translation changed')
    for name,sha in plan['input_sha256'].items():
        if digest(Path(name))!=sha:raise ValueError('Original evidence changed')
    run([ffmpeg,'-v','error','-xerror','-i',video,'-f','null','-'])
    hashes=[run([ffmpeg,'-v','error','-i',p,'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip()
            for p in (Path(plan['assets']['video']),video)]
    if hashes[0]!=hashes[1]:raise ValueError('Original picture differs')
    return video,subtitle,report,float(probe(video,ffmpeg)['format']['duration'])


def verify_s3_checksum(video,sha,head):
    """Compare AWS's cryptographic object checksum, never user metadata.

    SHA256 composite calculation follows the AWS multipart checksum tutorial.
    Our upload uses fixed 5 MiB parts; other partition layouts fall back to GET.
    """
    value=head.get('ChecksumSHA256')
    if not value:return False
    size=video.stat().st_size
    if head.get('ContentLength')!=size:raise ValueError('Remote length differs')
    whole=hashlib.sha256();composite=hashlib.sha256();parts=0
    with video.open('rb') as stream:
        while chunk:=stream.read(5*1024**2):
            whole.update(chunk);composite.update(hashlib.sha256(chunk).digest());parts+=1
    if whole.hexdigest()!=sha:raise ValueError('Local video changed during upload')
    full=base64.b64encode(whole.digest()).decode()
    combined=base64.b64encode(composite.digest()).decode()+f'-{parts}'
    return ((head.get('ChecksumType')=='FULL_OBJECT' and value==full) or
            (head.get('ChecksumType')=='COMPOSITE' and value==combined))


def s3_video(video,sha,config,folder):
    import boto3
    import requests
    from botocore.config import Config
    from boto3.s3.transfer import TransferConfig
    cfg=read_json(config)
    if cfg.get('bucket')!='starlitshorts' or cfg.get('prefix','').strip('/')!='aigc/drama/dubbing-video/carmilla-20261009':
        raise ValueError('Unexpected film storage scope')
    kwargs={}
    if cfg.get('ak') and cfg.get('sk'):kwargs={'aws_access_key_id':cfg['ak'],'aws_secret_access_key':cfg['sk']}
    elif boto3.Session().get_credentials() is None:raise ValueError('S3 credentials unavailable')
    if cfg.get('session_token'):kwargs['aws_session_token']=cfg['session_token']
    s3=boto3.client('s3',region_name=cfg.get('region','us-east-1'),
        config=Config(connect_timeout=15,read_timeout=60,retries={'max_attempts':3}),**kwargs)
    bucket=cfg['bucket'];key=cfg['prefix'].strip('/')+'/season-revisions/'+video.stem+'-'+sha+'.mp4'
    size=video.stat().st_size;url=f'https://{bucket}.s3.amazonaws.com/{key}'
    bind(folder/'s3-input.json',{'sha256':sha,'bytes':size,'bucket':bucket,'key':key})
    try:head=s3.head_object(Bucket=bucket,Key=key)
    except s3.exceptions.ClientError as exc:
        if str(exc.response['Error']['Code']) not in ('404','NoSuchKey','NotFound'):raise RuntimeError('S3 check failed') from None
        head=None
    if head is not None and (head['ContentLength']!=size or head.get('Metadata',{}).get('sha256')!=sha):
        raise ValueError('Existing object differs; no overwrite')
    receipt=folder/'upload.private.json'
    if head is not None and receipt.exists():
        old=read_json(receipt)
        if (old.get('url'),old.get('sha256'),old.get('bytes'),old.get('remote_sha256_verified'))==(url,sha,size,True):
            return url
    if head is None:
        s3.upload_file(str(video),bucket,key,ExtraArgs={'ContentType':'video/mp4','Metadata':{'sha256':sha},'ChecksumAlgorithm':'SHA256'},
                       Config=TransferConfig(multipart_threshold=5*1024**2,multipart_chunksize=5*1024**2,max_concurrency=3))
    checksum_head=s3.head_object(Bucket=bucket,Key=key,ChecksumMode='ENABLED')
    method='s3_sha256_checksum' if verify_s3_checksum(video,sha,checksum_head) else 'full_range_get_sha256'
    if method=='full_range_get_sha256' and parallel_remote_digest(s3,bucket,key,size)!=sha:
        raise ValueError('Remote content differs')
    if requests.head(url,timeout=20).status_code!=200:raise ValueError('Video not publicly readable')
    save_json(folder/'upload.private.json',{'url':url,'sha256':sha,'bytes':size,'remote_sha256_verified':True,'verification_method':method,
        'aws_checksum_type':checksum_head.get('ChecksumType'),'aws_checksum_sha256':checksum_head.get('ChecksumSHA256')})
    return url


def version_history(client,asset,n):
    rows=client.call('getReviewMaterialHistory',{'projectId':148,'gateType':'FINAL_CUT','assetId':asset})
    if not rows or any((r['projectId'],r['gateType'],r['name'])!=(148,'FINAL_CUT',f'Carmilla | EP.{n:02} | pt-BR') for r in rows):
        raise ValueError('Unexpected Review version scope')
    return rows


def append_version(client,n,url,sha,duration,folder):
    name=f'Carmilla | EP.{n:02} | pt-BR'
    current=[r for r in materials(client,148) if r.get('gateType')=='FINAL_CUT' and r.get('name')==name]
    if len(current)!=1:raise ValueError('Expected one existing film episode')
    rows=version_history(client,current[0]['assetId'],n)
    intent=folder/'version-intent.private.json'
    if not intent.exists():
        if any(r.get('url')==url for r in rows):raise ValueError('Existing candidate without local intent; reconcile first')
        newest=max(rows,key=lambda r:r['version'])
        spec={k:None for k in ('artDirectionSubMaterials','category','createdAt','documentKind','parentAssetId','status','updatedAt','version')}
        spec.update({'assetId':newest['assetId'],'projectId':148,'gateType':'FINAL_CUT','name':name,'url':url,
            'durationSeconds':round(duration),'tags':sorted(set(newest.get('tags') or [])|{'Carmilla','pt-BR','Cartesia','MiniMax'}),
            'note':('Full-season revision candidate using EP02 professional feedback. Existing voices; zero new clones. '
                    'Original picture retained; natural Brazilian Portuguese text and bounded timing. '
                    'Brazilian accent, pronunciation, emotion, timbre and source-stem contamination require professional listening. '
                    'Not native-approved. '+(f'EP{n:02} mix/source-isolation review still required. ' if n in (13,31) else '')+
                    'SHA256: '+sha)})
        save_json(intent,{'material':spec,'expected_version':newest['version']+1,
                          'before':[[r['assetId'],r['version']] for r in rows]})
    data=read_json(intent);spec=data['material'];bind(folder/'version-input.json',data)
    if spec['url']!=url or sha not in spec['note'] or spec['name']!=name:raise ValueError('Publication intent changed')
    before=data['before']
    if (not before or (spec.get('projectId'),spec.get('gateType'))!=(148,'FINAL_CUT')
            or spec['assetId']!=max(before,key=lambda x:x[1])[0]
            or data['expected_version']!=max(x[1] for x in before)+1
            or not {tuple(x) for x in before}.issubset({(r['assetId'],r['version']) for r in rows})
            or not {'Carmilla','pt-BR'}.issubset(set(spec.get('tags') or []))):
        raise ValueError('Publication intent belongs to another version scope')
    existing=[r for r in rows if r.get('url')==url]
    if not existing:
        if {(r['assetId'],r['version']) for r in rows}!={tuple(x) for x in data['before']}:
            raise ValueError('Concurrent Review version change; reconcile first')
        safe_submit(client,'updateReviewMaterialVersion',{'material':spec},folder/'version-submission.private.json')
    rows=version_history(client,spec['assetId'],n)
    existing=[r for r in rows if r.get('url')==url]
    if (len(existing)!=1 or existing[0]['version']!=data['expected_version']
            or not {tuple(x) for x in data['before']}.issubset({(r['assetId'],r['version']) for r in rows})
            or not {'Carmilla','pt-BR'}.issubset(set(existing[0].get('tags') or []))):
        raise ValueError('New version/old history readback failed')
    save_json(folder/'history-after.private.json',rows)
    return existing[0]


def publish(n,folder,args):
    video,subtitle,report,duration=validate_candidate(n,folder,args.ffmpeg)
    sha=report['output_sha256'];out=PUBLICATION/f'episode-{n:02}'/sha
    out.mkdir(parents=True,exist_ok=True)
    with process_lock(out/'publication.lock',timeout=0):
        bind(out/'candidate.json',{'folder':str(folder),'video_sha256':sha,'subtitle_sha256':digest(subtitle),
                                  'plan_sha256':digest(folder/'plan.json')})
        url=s3_video(video,sha,args.s3_config,out);client=Mflix(args.mcp_config)
        row=append_version(client,n,url,sha,duration,out)
        sub=out/'subtitle-upload.private.json'
        if not sub.exists():save_json(sub,{'url':client.upload(subtitle),'sha256':digest(subtitle)})
        uploaded=read_json(sub)
        if uploaded['sha256']!=digest(subtitle):raise ValueError('Subtitle changed')
        import requests
        response=requests.get(uploaded['url'],timeout=60);response.raise_for_status()
        if response.content!=subtitle.read_bytes():raise ValueError('Remote subtitle differs')
        ledger=out/'subtitle-registration.private.json'
        spec={'projectId':148,'gateType':'DOCUMENT','documentKind':'DOCUMENT',
              'name':f'Carmilla | EP.{n:02} | pt-BR subtitles | {sha[:12]}',
              'url':uploaded['url'],'tags':['Carmilla','pt-BR'],'note':f'SRT for video asset {row["assetId"]}, version {row["version"]}; video SHA256 {sha}; subtitle SHA256 {digest(subtitle)}.'}
        subtitle_asset=register(client,spec,read_json(ledger) if ledger.exists() else {'items':{}},ledger)
        result={'episode':n,'video_sha256':sha,'asset_id':row['assetId'],'version':row['version'],
                'url':url,'subtitle_asset_id':subtitle_asset,'subtitle_url':uploaded['url'],'subtitle_sha256':digest(subtitle),
                'native_listening_passed':False,'prior_versions_retained':True,'verified_at':time.time()}
        save_json(out/'publication-result.json',result)
        print('SEASON_PUBLISHED',n,row['assetId'],row['version'],flush=True)
        return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--s3-config',required=True,type=Path)
    p.add_argument('--mcp-config',required=True,type=Path);p.add_argument('--ffmpeg',required=True,type=Path)
    p.add_argument('--wait-for-lock',type=int,default=0,help='Bounded wait for another publisher; never resubmit uncertain mutations')
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business publication runs on Windows')
    if not 0<=args.wait_for_lock<=14400:p.error('Publication lock wait must be 0..14400 seconds')
    PUBLICATION.mkdir(parents=True,exist_ok=True)
    with process_lock(PUBLICATION/'season-publication.lock',timeout=args.wait_for_lock):
        status={'published':{},'requires_review':{},'all_32_published':False}
        for n,folder in sorted(candidates().items()):
            try:status['published'][str(n)]=publish(n,folder,args)
            except Exception as exc:
                status['requires_review'][str(n)]={'type':type(exc).__name__,'detail':str(exc)}
                print('PUBLICATION_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
            save_json(PUBLICATION/'progress.json',status)
        status['all_32_published']=set(status['published'])=={str(i) for i in range(1,33)}
        save_json(PUBLICATION/'progress.json',status)
        if not status['all_32_published']:raise SystemExit(2)


if __name__=='__main__':main()
