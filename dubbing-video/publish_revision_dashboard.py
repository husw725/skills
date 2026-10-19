"""Publish the existing S3 page from delivered season revisions; reuse uploaded videos."""
import argparse
from pathlib import Path
import time,sys,hashlib,os
from urllib.parse import urlsplit,unquote,quote
from dub_episode import digest
from translate import read_json,save_json
from process_lock import process_lock
from publish_dashboard import collect,build_html,safe_read
from publish_season_candidates import PUBLICATION,ROOTS,candidates
from rerun_carmilla_season import validate_reviewed_plan


def delivery(n,folder,receipt,base,prefix,validated):
    plan=read_json(folder/'plan.json');validate_reviewed_plan(folder,plan)
    report=read_json(folder/'render-report.json')
    video=folder/f'Carmilla_EP{n:02}_pt-BR_season-revision.mp4'
    subtitle=folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt'
    if (plan['episode']!=n or plan['project_id']!=59 or plan['blocking_issues']
            or receipt['episode']!=n or not receipt.get('asset_id') or not receipt.get('subtitle_asset_id')
            or receipt.get('prior_versions_retained') is not True
            or report['status']!='rendered_season_revision_candidate' or report['episode']!=n
            or not report['video_payload_identical'] or report['source_audio_in_output'] or report['new_clone_count']!=0
            or report['output_sha256']!=receipt['video_sha256']
            or digest(subtitle)!=receipt['subtitle_sha256'] or digest(subtitle)!=plan['translation_srt_sha256']
            or digest(folder/'reviewed.json')!=plan['reviewed_response_sha256']
            or digest(folder/'screenplay-context.json')!=plan['reviewed_context_sha256']):
        raise ValueError('Only version-matched delivered video and subtitle may enter the page')
    url=urlsplit(receipt['url']);origin=urlsplit(base);key=unquote(url.path).lstrip('/')
    if (url.scheme!='https' or url.netloc!=origin.netloc or url.query or url.fragment
            or not key.startswith(prefix+'videos/') or '..' in key.split('/')):
        raise ValueError('Reuse only existing unsigned videos under the approved S3 destination')
    stat=video.stat();cache_key=(str(video),stat.st_size,stat.st_mtime_ns,report['output_sha256'],digest(folder/'plan.json'),digest(folder/'render-report.json'))
    if cache_key not in validated:
        if digest(video)!=report['output_sha256']:raise ValueError('Delivered local video changed')
        validated.add(cache_key)
    return report,subtitle,key


def subtitle_link(n,path,receipt,state,s3,bucket,prefix,base,state_path=None):
    sha=receipt['subtitle_sha256'];video_sha=receipt['video_sha256'];subtitles=state.setdefault('subtitles',{})
    name=f'Carmilla_EP{n:02}_pt-BR.srt';key=prefix+f'subtitles/episode-{n:02}/{sha[:12]}/{name}'
    old=subtitles.get(str(n),{})
    if old.get('sha256')==sha and old.get('video_sha256')==video_sha and old.get('key')==key:
        return base+quote(old['key'])
    s3.upload_file(str(path),bucket,key,ExtraArgs={'ContentType':'application/x-subrip; charset=utf-8',
        'ContentDisposition':f'attachment; filename="{name}"','CacheControl':'public,max-age=86400',
        'Metadata':{'sha256':sha,'video-sha256':video_sha}})
    head=s3.head_object(Bucket=bucket,Key=key)
    if head['ContentLength']!=path.stat().st_size or head.get('Metadata',{}).get('sha256')!=sha or head.get('Metadata',{}).get('video-sha256')!=video_sha:
        raise ValueError('Final subtitle upload verification failed')
    response=s3.get_object(Bucket=bucket,Key=key)
    body=response['Body']
    try:uploaded=body.read()
    finally:body.close()
    if hashlib.sha256(uploaded).hexdigest()!=sha:raise ValueError('Final SRT object bytes differ')
    subtitles[str(n)]={'key':key,'sha256':sha,'video_sha256':video_sha,'uploaded_at':time.time()}
    if state_path is not None:save_json(state_path,state)
    return base+quote(key)


def snapshot(project,state,s3,bucket,prefix,validated):
    base=f'https://{bucket}.s3.amazonaws.com/'
    status=collect(project,{},base);episodes=[];published=0;ready=0
    current=None;detail='等待新版成片发布';production='running'
    available=candidates()
    for n in range(1,33):
        row={'episode':n,'assets_ready':status['episodes'][n-1]['assets_ready'],'status':'waiting','status_label':'等待新版'}
        relative=available.get(n)
        if relative:
            folder=project/relative;report=read_json(folder/'render-report.json')
            receipt_path=project/PUBLICATION/f'episode-{n:02}'/report['output_sha256']/'publication-result.json'
            if receipt_path.is_file():
                receipt=read_json(receipt_path);report,sub,key=delivery(n,folder,receipt,base,prefix,validated)
                row.update(status='completed',status_label='播放新版',video_url=base+quote(key),
                    subtitle_url=subtitle_link(n,sub,receipt,state,s3,bucket,prefix,base,project/'output/dashboard/season-publication-state.json'),duration_seconds=report['duration_seconds'],
                    timing_review_count=sum(u['atempo_factor']>1.15 for u in report['utterances']))
                published+=1;ready+=1
            else:row.update(status='uploading',status_label='新版待发布');ready+=1
        if row['status']!='completed' and not relative:
            for root in reversed(ROOTS):
                progress=safe_read(project/root/'season-progress.json',{})
                entry=progress.get('episodes',{}).get(str(n),{})
                active=progress.get('episode')==n
                if not entry and not active:continue
                stage=progress.get('stage') if active else entry.get('stage')
                if (project/root/f'episode-{n:02}/plan.json').is_file() and not relative:ready+=1
                if stage=='editorial':production='running';row.update(status='translated',status_label='新版译文审核中');current=n;detail=f'第 {n} 集新版译文审核中'
                elif stage=='rendering':
                    production='running'
                    p=safe_read(project/root/f'episode-{n:02}/progress.json',{})
                    row.update(status='rendering',status_label='新版音频处理中');current=n;detail=f'第 {n} 集音频 {p.get("complete",0)}/{p.get("total","—")} 段'
                elif entry.get('stage')=='requires_review' or stage=='requires_review':
                    row.update(status='waiting',status_label='新版待复核')
                    if current is None:current=n;detail=f'第 {n} 集需复核，已有音频和断点保留';production='stopped'
                elif entry.get('stage')=='editorial_ready':row.update(status='translated',status_label='新版译文已审')
                break
        episodes.append(row)
    if published==32:current=None;detail='32 集新版视频和对应字幕均已交付；待专业听审';production='complete'
    elif current is None:current=next(e['episode'] for e in episodes if e['status']!='completed')
    status.update(episodes=episodes,complete=published==32,updated_at=time.time())
    status['summary'].update(playable=published,current_episode=current,current_detail=detail,production_stage=production,
        editorial_ready=ready,translation_stage='translating' if '审核中' in detail else 'ready',
        translation_detail=f'新版视频及对应字幕已交付 {published}/32 集；文本与技术检查不代替巴葡母语听审。')
    return status


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True,type=Path)
    p.add_argument('--once',action='store_true');p.add_argument('--interval',type=int,default=600)
    a=p.parse_args()
    if sys.platform!='win32':p.error('Business publication runs on Windows')
    if a.interval<60:p.error('History interval must be >=60 seconds')
    import boto3
    from botocore.config import Config
    cfg=read_json(a.config);bucket=cfg.get('bucket','starlitshorts');prefix=cfg['prefix'].strip('/')+'/'
    if bucket!='starlitshorts' or prefix!='aigc/drama/dubbing-video/carmilla-20261009/':raise ValueError('Use the existing user-approved page destination')
    credentials={}
    if cfg.get('ak') and cfg.get('sk'):credentials={'aws_access_key_id':cfg['ak'],'aws_secret_access_key':cfg['sk']}
    if cfg.get('session_token'):credentials['aws_session_token']=cfg['session_token']
    s3=boto3.client('s3',region_name=cfg.get('region','us-east-1'),config=Config(retries={'max_attempts':5,'mode':'standard'}),**credentials)
    project=Path(__file__).resolve().parent;os.chdir(project);folder=project/'output/dashboard';folder.mkdir(parents=True,exist_ok=True)
    with process_lock(folder/'season-dashboard.lock',timeout=0):
        state_path=folder/'season-publication-state.json';old=safe_read(folder/'publication-state.json',{})
        state=safe_read(state_path,{'history':old.get('history',[]),'subtitles':{},'last_history':0});validated=set()
        while True:
            try:
                data=snapshot(project,state,s3,bucket,prefix,validated)
                summary=data['summary'];message=f"新版成片及字幕 {summary['playable']}/32；{summary['current_detail']}"
                if time.time()-state.get('last_history',0)>=a.interval or data['complete']:
                    state['history'].append({'time':time.time(),'message':message});state['history']=state['history'][-200:];state['last_history']=time.time()
                data['history']=state['history'];save_json(folder/'season-status.json',data)
                template=(project/'dashboard.html').read_text(encoding='utf-8').replace('巴西葡语配音 · 32 集 · 原画面保留','新版巴西葡语配音 · 32 集 · 原画面保留')
                html=build_html(template,data);(folder/'season-index.html').write_text(html,encoding='utf-8')
                s3.put_object(Bucket=bucket,Key=prefix+'index.html',Body=html.encode(),ContentType='text/html; charset=utf-8',CacheControl='no-cache,max-age=0')
                save_json(state_path,state);print('REVISION_PAGE_PUBLISHED',summary['playable'],flush=True)
                if a.once or data['complete']:return
            except Exception as exc:
                save_json(folder/'season-publisher-error.private.json',{'time':time.time(),'type':type(exc).__name__})
                if a.once:raise
            time.sleep(30)


if __name__=='__main__':main()
