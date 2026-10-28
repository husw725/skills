"""Finite Windows job; independent final-media approval/publication stays separate."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from translate import read_json,save_json,fingerprint
from dub_episode import digest
from process_lock import process_lock
import contextual_ptbr_candidate as pipeline


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ffmpeg',type=Path,required=True)
    p.add_argument('--mcp-config',type=Path,required=True)
    p.add_argument('--variant',choices=['alignment-v3','feedback-oct28'],default='alignment-v3');a=p.parse_args()
    if sys.platform!='win32':p.error('Launch on Windows only')
    if a.variant=='feedback-oct28':
        from feedback_repair_oct28 import configure
        configure()
    else:pipeline.configure_alignment_revision()
    root=pipeline.ROOT
    m=read_json(root/'manifest.private.json');pipeline.validate(m)
    with process_lock(root/'windows-job.lock',timeout=0):
        state_path=root/'windows-job-state.private.json'
        if state_path.exists():
            old=read_json(state_path)
            if old['manifest_fingerprint']!=fingerprint(m):raise ValueError('Another job basis exists')
            if old['status']=='ready_for_independent_media_review':
                for path,sha in old['artifact_sha256'].items():
                    if digest(path)!=sha:raise ValueError('Ready artifact changed')
                print('WINDOWS_CONTEXT_JOB_ALREADY_READY',flush=True);return
        state={'manifest_fingerprint':fingerprint(m),'status':'running','started_at':time.time(),
          'new_request_cap':m['paid_request_cap'],'new_clone_count':0,'publication_attempted':False}
        save_json(state_path,state)
        env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
        for k in list(env):
            if k.lower() in ('http_proxy','https_proxy','all_proxy'):env.pop(k)
        script='feedback_repair_oct28.py' if a.variant=='feedback-oct28' else 'contextual_ptbr_alignment_v3.py'
        base=[sys.executable,script]
        asr=[str(Path('output/tools/asr-venv/Scripts/python.exe')),script]
        steps=[('generate',base+['--stage','generate','--ffmpeg',str(a.ffmpeg),'--mcp-config',str(a.mcp_config)]),
          ('fit',base+['--stage','fit','--ffmpeg',str(a.ffmpeg)]),
          ('screen',asr+['--stage','screen','--ffmpeg',str(a.ffmpeg)]),
          ('render',base+['--stage','render','--ffmpeg',str(a.ffmpeg)])]
        with (root/'windows-job.log').open('a',encoding='utf-8') as log:
            for stage,command in steps:
                state.update(stage=stage,updated_at=time.time());save_json(state_path,state)
                try:
                    result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900)
                except (OSError,subprocess.TimeoutExpired) as exc:
                    state.update(status='failed',error_type=type(exc).__name__,finished_at=time.time(),
                      reconciliation_required=stage=='generate');save_json(state_path,state)
                    print('WINDOWS_CONTEXT_JOB_STOPPED',stage,type(exc).__name__,flush=True)
                    raise SystemExit(1)
                if result.returncode:
                    state.update(status='blocked' if stage=='fit' and result.returncode==2 else 'failed',
                      exit_code=result.returncode,finished_at=time.time());save_json(state_path,state)
                    print('WINDOWS_CONTEXT_JOB_STOPPED',stage,result.returncode,flush=True)
                    raise SystemExit(2 if stage=='fit' and result.returncode==2 else 1)
        report=read_json(root/'render-report.private.json')
        for path,sha in report['artifact_sha256'].items():
            if digest(path)!=sha:raise ValueError('Final artifact changed')
        state.update(status='ready_for_independent_media_review',artifact_sha256=report['artifact_sha256'],finished_at=time.time())
        save_json(state_path,state);print('WINDOWS_CONTEXT_JOB_READY',flush=True)


if __name__=='__main__':main()
