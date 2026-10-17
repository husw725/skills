"""Send the requested one-time completion notice only after all 32 Review deliveries exist."""
import argparse
import contextlib
import importlib.util
import io
from pathlib import Path
import socket
import sys
import time

from mflix_client import Mflix
from process_lock import process_lock
from publish_review import materials
from publish_season_candidates import PUBLICATION
from translate import fingerprint,read_json,save_json


def verify_delivery(progress,rows):
    published=progress.get('published',{})
    if not progress.get('all_32_published') or progress.get('requires_review') or set(published)!={str(n) for n in range(1,33)}:
        raise ValueError('Full season is not published; no completion notification')
    by_id={r['assetId']:r for r in rows}
    if len({r['asset_id'] for r in published.values()})!=32 or len({r['subtitle_asset_id'] for r in published.values()})!=32:
        raise ValueError('Episode delivery IDs are not unique')
    for n in range(1,33):
        result=published[str(n)];video=by_id.get(result['asset_id']);subtitle=by_id.get(result['subtitle_asset_id'])
        if not video or not subtitle:raise ValueError('Missing video or subtitle in live Review project')
        if (result['episode']!=n or video.get('projectId')!=148 or video.get('gateType')!='FINAL_CUT'
                or video.get('name')!=f'Carmilla | EP.{n:02} | pt-BR' or video.get('url')!=result['url']
                or video.get('version')!=result['version'] or not {'Carmilla','pt-BR'}.issubset(set(video.get('tags') or []))
                or subtitle.get('projectId')!=148 or subtitle.get('gateType')!='DOCUMENT'
                or subtitle.get('name')!=f'Carmilla | EP.{n:02} | pt-BR subtitles | {result["video_sha256"][:12]}'
                or not result.get('subtitle_url') or subtitle.get('url')!=result['subtitle_url']
                or subtitle.get('documentKind')!='DOCUMENT'
                or not {'Carmilla','pt-BR'}.issubset(set(subtitle.get('tags') or []))
                or result['subtitle_sha256'] not in subtitle.get('note','')
                or not result.get('prior_versions_retained')):raise ValueError('Live Review delivery does not match this season')
    return published


def send_private(sender,url,message):
    # The bundled skill prints raw transport errors. Keep those in memory only,
    # and bound its urllib calls without changing any host/network settings.
    old_timeout=socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(30)
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            sender.send_message(url,message)
    except (Exception,SystemExit):
        raise RuntimeError('DingTalk send failed; outcome uncertain, pending retained') from None
    finally:socket.setdefaulttimeout(old_timeout)


def main():
    p=argparse.ArgumentParser();p.add_argument('--mcp-config',required=True,type=Path)
    p.add_argument('--dingtalk-config',required=True,type=Path);p.add_argument('--sender-script',required=True,type=Path)
    a=p.parse_args()
    if sys.platform!='win32':p.error('Completion notification is executed on Windows')
    with process_lock(PUBLICATION/'completion-notification.lock',timeout=0):
        receipt=PUBLICATION/'completion-notification.json';pending=PUBLICATION/'completion-notification.pending.json'
        if receipt.exists():print('COMPLETION_NOTICE_ALREADY_SENT',flush=True);return
        if pending.exists():raise ValueError('Earlier notice outcome uncertain; do not automatically send twice')
        progress=read_json(PUBLICATION/'progress.json')
        client=Mflix(a.mcp_config);published=verify_delivery(progress,materials(client,148))
        config=read_json(a.dingtalk_config);url=config['webhook_url']
        if not url.startswith('https://oapi.dingtalk.com/robot/send?'):raise ValueError('Unexpected configured webhook')
        message=('### Carmilla 巴葡配音任务：新版已上传 Review\n\n32/32 集新版成片及对应字幕已上传，旧版本保留。'
                 '\n\nReview 项目：PT Transalte（148）。请查看 Carmilla 各集最新版本。'
                 '\n\n本轮按第 2 集专业反馈优化巴葡译文、发音处理和时长，复用已有音色，未新增克隆。'
                 '口音、情绪表演、音色衔接和混音仍请专业人员听审；这条通知表示交付完成，不表示母语验收通过。')
        signature=fingerprint({'message':message,'deliveries':published})
        spec=importlib.util.spec_from_file_location('dingtalk_skill_sender',a.sender_script)
        sender=importlib.util.module_from_spec(spec);spec.loader.exec_module(sender)
        save_json(pending,{'fingerprint':signature,'started_at':time.time(),'project_id':148,'episodes':32})
        send_private(sender,url,message)
        save_json(receipt,{'fingerprint':signature,'sent_at':time.time(),'project_id':148,'episodes':32})
        pending.unlink()


if __name__=='__main__':main()
