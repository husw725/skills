"""Measure all remaining paid groups before a final isolated timing revision."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from repair_carmilla_measured import selected_pending
from process_lock import process_lock
from translate import read_json,save_json

ROOT=Path('output/carmilla-season-timing-repair2-20261017')


def main():
    p=argparse.ArgumentParser()
    for flag in ('codex-exe','mcp-config','ffmpeg'):p.add_argument('--'+flag,required=True,type=Path)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,k).is_file() for k in ('codex_exe','mcp_config','ffmpeg')):p.error('Existing executables/config required')
    args.finalize_pending=True;args.source_evidence=False
    args.cache_roots=[season.TIMING_ROOT,season.FINAL_ROOT,season.RETRY_ROOT,season.BASE_ROOT]
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        baseline=read_json(season.TIMING_ROOT/'season-progress.json')
        state=read_json(ROOT/'season-progress.json') if (ROOT/'season-progress.json').exists() else {'episodes':{}}
        episodes=selected_pending(baseline,state)
        state.update(selected_episodes=episodes,started_at=time.time(),native_acceptance_passed=False)
        preceding=[]
        for n in episodes:
            try:
                # Only this whitelisted timing-failed plan; no source-error or
                # completed episode enters. All immutable plan/input, role,
                # frozen-bank and every prior pending guard run before payment.
                season.ROOT=season.TIMING_ROOT;args.prior_root=season.FINAL_ROOT;args.measure_only=True
                with process_lock(season.ROOT/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                season.ROOT=ROOT;args.prior_root=season.TIMING_ROOT;args.measure_only=False
                preceding.append(season.prepare(n,args,preceding))
                state['episodes'][str(n)]={'stage':'editorial_ready'};save_json(ROOT/'season-progress.json',state)
                with process_lock(ROOT/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                state['episodes'][str(n)]={'stage':'rendered_candidate'}
            except Exception as exc:
                state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                print('FULL_MEASURED_REPAIR_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
            state['updated_at']=time.time();save_json(ROOT/'season-progress.json',state)
        state['stage']='selected_candidates_complete' if all(r['stage']=='rendered_candidate' for r in state['episodes'].values()) else 'requires_review'
        save_json(ROOT/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
