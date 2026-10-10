"""Independent Windows stop watcher; secrets and delivery receipts stay in output."""
import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

from process_lock import process_lock
from translate import fingerprint,read_json,save_json

PAGE='https://starlitshorts.s3.amazonaws.com/aigc/drama/dubbing-video/carmilla-20261009/index.html'


def events(root,now):
    result=[]
    for name,label in [('queue','配音生产'),('translation','翻译')]:
        path=root/f'output/drama-01/{name}-progress.json'
        if not path.exists():continue
        try:state=read_json(path)
        except (OSError,ValueError):continue
        stage=state.get('stage');updated=state.get('updated_at',now)
        if stage=='stopped':
            result.append({'worker':name,'episode':state.get('episode'),'kind':'stopped','occurrence':updated,
                           'reason':state.get('public_detail') or f"{label}异常停止（{state.get('detail','原因待核查')}）"})
        elif name=='queue' and stage in ('waiting','rendering') and now-updated>120:
            result.append({'worker':name,'episode':state.get('episode'),'kind':'heartbeat','occurrence':updated,
                           'reason':'生产进度超过两分钟未更新，可能已退出，请核查 Windows 工作进程'})
        elif name=='queue' and stage=='waiting':
            translation=root/'output/drama-01/translation-progress.json'
            if translation.exists():
                t=read_json(translation)
                if state.get('episode') in t.get('pending_episodes',[]):
                    result.append({'worker':name,'episode':state['episode'],'kind':'review','occurrence':t.get('updated_at'),
                                   'reason':'该集剧本/字幕版本或文本审核待核查，生产等待审核通过的译稿'})
    return result


def send(cfg,message):
    # Adapted from the dingtalk-sender skill's Markdown sender, with timeout,
    # signing support and sanitized failures. No webhook in process arguments.
    url=cfg['webhook_url'];parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='oapi.dingtalk.com' or parsed.path!='/robot/send':
        raise ValueError('Invalid DingTalk robot endpoint')
    if cfg.get('secret'):
        stamp=str(int(time.time()*1000));secret=cfg['secret']
        signature=base64.b64encode(hmac.new(secret.encode(),f'{stamp}\n{secret}'.encode(),hashlib.sha256).digest()).decode()
        url+='&'+urllib.parse.urlencode({'timestamp':stamp,'sign':signature})
    data={'msgtype':'markdown','markdown':{'title':'短剧任务停止通知','text':message}}
    req=urllib.request.Request(url,data=json.dumps(data,ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json; charset=utf-8'})
    with urllib.request.urlopen(req,timeout=20) as response:result=json.load(response)
    if result.get('errcode')!=0:raise RuntimeError(f"DingTalk rejected notification, code {result.get('errcode')}")


def tick(root,config):
    folder=root/'output/notifications';folder.mkdir(parents=True,exist_ok=True)
    if not config.exists():
        save_json(folder/'watch-status.json',{'stage':'needs_configuration','updated_at':time.time()});return
    cfg=read_json(config)
    with process_lock(folder/'delivery.lock',timeout=0):
        path=folder/'delivery-state.private.json';state=read_json(path) if path.exists() else {'events':{}}
        for event in events(root,time.time()):
            key=fingerprint(event)
            if key in state['events']:continue
            # Persist before the network call: a timeout must not spam retries.
            state['events'][key]={'event':event,'status':'sending','attempted_at':time.time()};save_json(path,state)
            number=event['episode'];episode=f'第 {number} 集' if number else '当前任务'
            message=f"### 短剧任务停止通知\n\nCarmilla · {episode}\n\n原因：{event['reason']}\n\n[查看进度]({PAGE})\n\n已保留断点；不会自动重复提交克隆或配音。"
            if cfg.get('keyword'):message=cfg['keyword']+'\n\n'+message
            try:send(cfg,message)
            except Exception as exc:
                state['events'][key].update(status='delivery_failed_or_unknown',error_type=type(exc).__name__)
            else:state['events'][key].update(status='sent',sent_at=time.time())
            save_json(path,state)
        save_json(folder/'watch-status.json',{'stage':'watching','updated_at':time.time(),
                  'sent':sum(e['status']=='sent' for e in state['events'].values()),
                  'failed_or_unknown':sum(e['status']=='delivery_failed_or_unknown' for e in state['events'].values())})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('output/dingtalk-notify.private.json'));p.add_argument('--once',action='store_true')
    args=p.parse_args()
    if sys.platform!='win32':p.error('Task monitoring runs on Windows')
    root=Path.cwd()
    with process_lock(root/'output/notifications/watch.lock',timeout=0):
        while True:
            try:tick(root,args.config)
            except Exception as exc:
                save_json(root/'output/notifications/watch-status.json',{'stage':'watch_error','error_type':type(exc).__name__,'updated_at':time.time()})
                if args.once:raise
            if args.once:break
            time.sleep(30)


if __name__=='__main__':main()
