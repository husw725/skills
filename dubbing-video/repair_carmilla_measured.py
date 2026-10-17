"""One isolated measured-duration repair; preserve every paid earlier attempt."""
import argparse
from pathlib import Path
import sys
import time

import rerun_carmilla_season as season
from process_lock import process_lock
from translate import read_json,save_json

ROOT=Path('output/carmilla-season-timing-repair-20261017')
ELIGIBLE={3,9,10,11,15,21,22,23,26,28,31,32}
TIMING_ERRORS={'Measured speech too long: revise faithfully; no automatic paid speed retries',
               'Cannot fit without truncating/over-speeding'}


def selected_pending(baseline,state):
    return [n for n in sorted(ELIGIBLE) if baseline['episodes'].get(str(n),{}).get('detail') in TIMING_ERRORS
            and baseline['episodes'][str(n)].get('stage')=='requires_review'
            and state['episodes'].get(str(n),{}).get('stage')!='rendered_candidate']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--codex-exe',required=True,type=Path)
    parser.add_argument('--mcp-config',required=True,type=Path)
    parser.add_argument('--ffmpeg',required=True,type=Path)
    parser.add_argument('--wait-for-production-lock',type=int,default=14400)
    args=parser.parse_args()
    if sys.platform!='win32':parser.error('Business execution stays on Windows')
    if not args.codex_exe.is_file() or not args.ffmpeg.is_file() or not args.mcp_config.is_file():
        parser.error('Existing executable/config files required')
    if not 0<=args.wait_for_production_lock<=14400:parser.error('Wait must be 0..14400 seconds')
    args.finalize_pending=True;args.source_evidence=False;args.prior_root=season.FINAL_ROOT
    args.cache_roots=[season.FINAL_ROOT,season.RETRY_ROOT,season.BASE_ROOT]
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(season.BASE_ROOT/'season.lock',timeout=args.wait_for_production_lock):
        baseline=read_json(season.FINAL_ROOT/'season-progress.json')
        state=read_json(ROOT/'season-progress.json') if (ROOT/'season-progress.json').exists() else {'episodes':{}}
        episodes=selected_pending(baseline,state)
        state.update({'selected_episodes':episodes,'started_at':time.time(),'native_acceptance_passed':False})
        season.ROOT=ROOT
        preceding=[]
        for n in episodes:
            try:
                # Recompute from the original timed source + screenplay, binding
                # current paid durations and reviewed FINAL translation as inputs.
                preceding.append(season.prepare(n,args,preceding))
                state['episodes'][str(n)]={'stage':'editorial_ready'}
                save_json(ROOT/'season-progress.json',state)
                with process_lock(ROOT/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                state['episodes'][str(n)]={'stage':'rendered_candidate'}
            except Exception as exc:
                state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                print('MEASURED_REPAIR_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
            state['updated_at']=time.time();save_json(ROOT/'season-progress.json',state)
        state['stage']='selected_candidates_complete' if all(e['stage']=='rendered_candidate' for e in state['episodes'].values()) else 'requires_review'
        save_json(ROOT/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
