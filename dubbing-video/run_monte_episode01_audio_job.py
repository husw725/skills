"""Run the approved first-episode paid stage once, then unpaid fit and rendering."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
from generate_monte_episode01 import ROOT
from process_lock import process_lock
from translate import read_json,save_json
from dub_episode import digest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mcp-config',required=True,type=Path)
    p.add_argument('--ffmpeg',required=True,type=Path);args=p.parse_args()
    if sys.platform!='win32':raise ValueError('Windows local job only')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'job.lock',timeout=0):
        finished=ROOT/'render-report.private.json'
        if finished.exists():
            report=read_json(finished)
            if (digest(report['output'])!=report['output_sha256']
                or report['plan_sha256']!=digest(ROOT/'speech-plan.private.json')):
                raise ValueError('Prior output or production plan changed')
            return
        for stage,command in [('generate',['generate_monte_episode01.py','--stage','generate','--mcp-config',str(args.mcp_config)]),
            ('fit_render',['fit_render_monte_episode01.py','--ffmpeg',str(args.ffmpeg)])]:
            save_json(ROOT/'job-state.private.json',{'stage':stage,'status':'running','updated_at':time.time()})
            with (ROOT/'job.private.log').open('a',encoding='utf-8') as log:
                process=subprocess.Popen([sys.executable,'-u',*command],stdout=log,stderr=log)
                try:code=process.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    save_json(ROOT/'job-state.private.json',{'stage':stage,'status':'timeout_needs_reconciliation',
                        'automatic_retry':False,'updated_at':time.time()})
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=25)
                    raise ValueError('Finite stage timed out; preserve all paid tasks') from None
            if code:
                save_json(ROOT/'job-state.private.json',{'stage':stage,'status':'needs_review',
                    'exit_code':code,'automatic_retry':False,'updated_at':time.time()})
                raise ValueError('Audio stage failed; inspect saved state without a new paid retry')
        if not finished.exists():
            save_json(ROOT/'job-state.private.json',{'stage':'fit_render','status':'blocked_no_new_paid_retry',
                'updated_at':time.time()});return
        save_json(ROOT/'job-state.private.json',{'stage':'episode_media_candidate_ready','status':'media_review_pending',
            'updated_at':time.time()})


if __name__=='__main__':main()
