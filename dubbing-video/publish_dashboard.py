"""Windows publisher: upload completed videos, publish status every ten minutes."""
import argparse
import json
from pathlib import Path
import time
import sys
from urllib.parse import quote

from dub_episode import digest
from translate import read_json,save_json


def safe_read(path,default):
    try:return read_json(path)
    except (OSError,ValueError):return default


def collect(project,published,base):
    episodes=[];assets_ready=0;playable=0;current=None;current_detail='等待下一集素材与译稿'
    downloads=safe_read(project/'output/downloads/download-progress.json',{})
    downloaded={int(e['episode']):e for e in downloads.get('episodes',[])}
    for number in range(1,33):
        episode_root=project/f'output/drama-01/episode-{number:02d}'
        media=safe_read(episode_root/'media/media-manifest.json',{})
        ready=all(media.get('assets',{}).get(k,{}).get('decode_verified') for k in ('video','bgm','sfx'))
        if not ready:ready=all(downloaded.get(number,{}).get('assets',{}).get(k,{}).get('verified') for k in ('video','bgm','sfx'))
        if ready:assets_ready+=1
        reports=list(episode_root.glob('dub-*/render-report.json'))
        report=safe_read(max(reports,key=lambda p:p.stat().st_mtime),{}) if reports else {}
        key=published.get(str(number),{}).get('key')
        status='waiting';label='等待素材';item={'episode':number,'assets_ready':bool(ready)}
        if ready:status='prepared';label='素材齐备'
        if (episode_root/'translation-v2/translated.json').exists() or (episode_root/'translation/translated.json').exists():status='translated';label='译文已准备'
        progress_paths=list(episode_root.glob('dub-*/progress.json'))
        if progress_paths and not report:
            progress=safe_read(max(progress_paths,key=lambda p:p.stat().st_mtime),{})
            status='rendering';label='配音进行中';current=number
            current_detail=f"配音 {len(progress.get('completed_units',[]))} / {progress.get('total_units','—')} 个单元"
        if report:
            status='uploading';label='待发布'
        if key and report and published[str(number)].get('sha256')==report.get('output_sha256'):
            status='completed';label='播放成片';playable+=1
            item.update(video_url=base+quote(key),duration_seconds=report.get('duration_seconds'),timing_review_count=report.get('timing_quality_review_count',0))
        item.update(status=status,status_label=label);episodes.append(item)
    if current is None:
        current=next((e['episode'] for e in episodes if e['status']!='completed'),None)
        if current:current_detail=next(e['status_label'] for e in episodes if e['episode']==current)
    bank=safe_read(project/'output/drama-01/voice-bank.json',{'voices':{}})
    queue=safe_read(project/'output/drama-01/queue-progress.json',{})
    if queue.get('stage')=='stopped':
        current_detail='生产队列已停止，等待核查；不会自动重复付费请求'
    elif queue.get('stage')=='waiting' and current==queue.get('episode'):
        current_detail=queue.get('detail',current_detail)
    return {'project':'Carmilla','language':'pt-BR','total_episodes':32,'updated_at':time.time(),
            'complete':playable==32,'summary':{'playable':playable,'assets_ready':assets_ready,'voices':len(bank['voices']),
                'current_episode':current,'current_detail':current_detail},'episodes':episodes}


def build_html(template,status):
    bootstrap=json.dumps(status,ensure_ascii=False).replace('<','\\u003c')
    return template.replace('__BOOTSTRAP__',bootstrap)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--config',required=True,type=Path)
    p.add_argument('--once',action='store_true');p.add_argument('--interval',type=int,default=600)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business publication runs on Windows')
    if args.interval<60:p.error('Publish interval must be >=60 seconds')
    import boto3
    from botocore.config import Config
    cfg=read_json(args.config);bucket=cfg.get('bucket','starlitshorts');prefix=cfg['prefix'].strip('/')+'/'
    if not prefix.startswith('aigc/drama/') or '..' in prefix.split('/'):
        raise ValueError('Use the user-approved team prefix')
    credentials={}
    if cfg.get('ak') and cfg.get('sk'):credentials={'aws_access_key_id':cfg['ak'],'aws_secret_access_key':cfg['sk']}
    if cfg.get('session_token'):credentials['aws_session_token']=cfg['session_token']
    s3=boto3.client('s3',region_name=cfg.get('region','us-east-1'),config=Config(retries={'max_attempts':5,'mode':'standard'}),**credentials)
    project=args.project_root.resolve();root=project/'output/dashboard';root.mkdir(parents=True,exist_ok=True)
    state_path=root/'publication-state.json';state=safe_read(state_path,{'videos':{},'history':[],'last_publish':0,'last_history':0})
    template=(project/'dashboard.html').read_text(encoding='utf-8');base=f'https://{bucket}.s3.amazonaws.com/'
    while True:
        try:
            changed=False
            latest_reports={}
            for candidate in (project/'output/drama-01').glob('episode-*/dub-*/render-report.json'):
                episode_folder=candidate.parent.parent.name
                if episode_folder not in latest_reports or candidate.stat().st_mtime>latest_reports[episode_folder].stat().st_mtime:
                    latest_reports[episode_folder]=candidate
            for report_path in sorted(latest_reports.values()):
                report=safe_read(report_path,{})
                if report.get('status')!='rendered_draft' or not report.get('video_payload_identical'):continue
                number=str(int(report['episode']));path=Path(report['output'])
                if not path.is_absolute():path=project/path
                if not path.is_file():continue
                expected=report['output_sha256']
                if state['videos'].get(number,{}).get('sha256')==expected:continue
                if digest(path)!=expected:raise ValueError('Rendered file hash mismatch; not published')
                key=prefix+f'videos/episode-{int(number):02d}/Carmilla_EP{int(number):02d}_pt-BR-{expected[:12]}.mp4'
                s3.upload_file(str(path),bucket,key,ExtraArgs={'ContentType':'video/mp4','CacheControl':'public,max-age=86400','Metadata':{'sha256':expected}})
                head=s3.head_object(Bucket=bucket,Key=key)
                if head['ContentLength']!=path.stat().st_size or head.get('Metadata',{}).get('sha256')!=expected:
                    raise ValueError('S3 video verification failed')
                state['videos'][number]={'key':key,'sha256':expected,'bytes':path.stat().st_size,'uploaded_at':time.time()}
                changed=True;save_json(state_path,state)
                print('VIDEO_PUBLISHED',number,flush=True)
            if changed or time.time()-state['last_publish']>=30 or args.once:
                status=collect(project,state['videos'],base)
                summary=status['summary'];message=f"成片 {summary['playable']}/32；素材齐备 {summary['assets_ready']}/32；可复用声音 {summary['voices']} 个。"
                if summary['current_episode']:message+=f"当前第 {summary['current_episode']} 集：{summary['current_detail']}。"
                if changed or time.time()-state.get('last_history',0)>=args.interval or args.once:
                    state['history'].append({'time':time.time(),'message':message});state['history']=state['history'][-200:]
                    state['last_history']=time.time()
                status['history']=state['history'];save_json(root/'status.json',status)
                html=build_html((project/'dashboard.html').read_text(encoding='utf-8'),status);(root/'index.html').write_text(html,encoding='utf-8')
                s3.put_object(Bucket=bucket,Key=prefix+'index.html',Body=html.encode(),ContentType='text/html; charset=utf-8',CacheControl='no-cache,max-age=0')
                state['last_publish']=time.time();save_json(state_path,state)
                print('STATUS_PUBLISHED',message,flush=True)
                if status['complete']:break
            if args.once:break
        except Exception as exc:
            save_json(root/'publisher-error.private.json',{'time':time.time(),'type':type(exc).__name__})
            print('PUBLISH_ERROR',type(exc).__name__,flush=True)
            if args.once:raise
        time.sleep(30)
    print('Dashboard:',base+prefix+'index.html',flush=True)


if __name__=='__main__':main()
