"""Prepare ahead concurrently; synthesize/render reviewed episodes in order on Windows."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time

from process_lock import process_lock
from translate import read_json, save_json
from dub_episode import digest


def rendered(folder):
    report=folder/'dub-v1/render-report.json'
    if not report.exists():return False
    data=read_json(report)
    path=Path(data['output'])
    if data.get('status')!='rendered_draft' or not data.get('video_payload_identical'):
        raise ValueError('Existing render report is not verified')
    if not path.exists() or digest(path)!=data['output_sha256']:
        raise ValueError('Existing rendered video hash differs; inspect before retry')
    return True


def prepare(episode,ffmpeg,bible):
    folder=Path(f'output/drama-01/episode-{episode:02d}');editorial=folder/'editorial'
    with process_lock(folder/'preparation.lock',timeout=0):
        # Preparation has no cloning/generation calls. A reviewed translation
        # with its matching screenplay fingerprint is mandatory.
        commands=[['export_translation.py',str(editorial/'source.json'),str(editorial/'translation.json'),
                   '--screenplay-context',str(editorial/'screenplay-context.json'),'--bible',str(bible),
                   '--output-dir',str(folder/'translation')],
                  ['build_episode_plan.py','--episode',str(episode),'--ffmpeg',str(ffmpeg)]]
        folder.mkdir(parents=True,exist_ok=True)
        with (folder/'preparation.log').open('a',encoding='utf-8') as log:
            for command in commands:subprocess.run([sys.executable,'-u',*command],stdout=log,stderr=log,check=True)
    return episode


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffmpeg',required=True,type=Path);p.add_argument('--mcp-config',required=True,type=Path)
    p.add_argument('--start-episode',type=int,default=1)
    p.add_argument('--bible',type=Path,default=Path('output/drama-01/episode-01/translation-v2/series-bible.json'))
    args=p.parse_args()
    if sys.platform!='win32':p.error('Production runs on Windows')
    if not 1<=args.start_episode<=32:p.error('Episode must be 1–32')
    root=Path('output/drama-01');state=root/'queue-progress.json'
    with process_lock(root/'production-queue.lock',timeout=0),ThreadPoolExecutor(max_workers=2) as pool:
        preparing={}
        for episode in range(args.start_episode,33):
            folder=root/f'episode-{episode:02d}'
            if rendered(folder):continue
            while True:
                for candidate in range(episode,min(32,episode+1)+1):
                    other=root/f'episode-{candidate:02d}'
                    if candidate in preparing or rendered(other):continue
                    if all((other/'editorial'/name).exists() for name in ('source.json','translation.json','screenplay-context.json')):
                        preparing[candidate]=pool.submit(prepare,candidate,args.ffmpeg,args.bible)
                # A resumed queue must also wait for the older in-flight episode.
                prior_ready=all((root/f'episode-{n:02d}/dub-v1/render-report.json').exists() for n in range(1,episode))
                future=preparing.get(episode)
                if future and future.done() and prior_ready:
                    future.result();break
                reason='等待已审译稿' if not future else ('等待前集完成' if not prior_ready else '准备素材与译稿')
                save_json(state,{'episode':episode,'stage':'waiting','detail':reason,'updated_at':time.time()})
                time.sleep(30)
            save_json(state,{'episode':episode,'stage':'rendering','detail':'逐句配音（三路并发）与合成','updated_at':time.time()})
            with (folder/'queue-render.log').open('a',encoding='utf-8') as log:
                subprocess.run([sys.executable,'-u','dub_episode.py',str(folder/'dub-plan-v1.json'),
                                '--mcp-config',str(args.mcp_config),'--ffmpeg',str(args.ffmpeg)],stdout=log,stderr=log,check=True)
            if not rendered(folder):raise RuntimeError('Renderer did not produce a verified report')
        save_json(state,{'stage':'complete','updated_at':time.time()})


if __name__=='__main__':
    try:main()
    except Exception as exc:
        save_json(Path('output/drama-01/queue-progress.json'),{'stage':'stopped','detail':type(exc).__name__,
                   'message':str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'See private runner log',
                   'updated_at':time.time()})
        raise
