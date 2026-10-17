"""One measured repair of the five remaining timing failures; keep prior attempts."""
import argparse
from pathlib import Path
import sys
import time

import rerun_carmilla_season as season
from process_lock import process_lock
from repair_carmilla_measured import TIMING_ERRORS
from translate import read_json,save_json

PRIORS={10:season.TIMING2_ROOT,18:season.FINAL_ROOT,22:season.TIMING2_ROOT,
        28:season.TIMING2_ROOT,32:season.TIMING2_ROOT}


def selected(priors,state):
    return [n for n,prior in sorted(priors.items())
            if state.get('episodes',{}).get(str(n),{}).get('stage')!='rendered_candidate'
            and read_json(prior/'season-progress.json')['episodes'].get(str(n),{}).get('stage')=='requires_review'
            and read_json(prior/'season-progress.json')['episodes'][str(n)].get('detail') in TIMING_ERRORS]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg'):p.add_argument('--'+name,required=True,type=Path)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,name).is_file() for name in ('codex_exe','mcp_config','ffmpeg')):
        p.error('Existing executables and private config required')
    args.finalize_pending=True;args.source_prior_root=season.RETRY_ROOT
    args.cache_roots=[r for r in season.paid_cache_roots() if r!=season.RESUME_ROOT]
    root=season.RESUME_ROOT;root.mkdir(parents=True,exist_ok=True)
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        state=read_json(root/'season-progress.json') if (root/'season-progress.json').exists() else {'episodes':{}}
        episodes=selected(PRIORS,state)
        state.update(selected_episodes=episodes,started_at=time.time(),native_acceptance_passed=False)
        preceding=[]
        for n in episodes:
            prior=PRIORS[n];args.prior_root=prior
            try:
                state.update(stage='measuring',episode=n,updated_at=time.time());save_json(root/'season-progress.json',state)
                season.ROOT=prior;args.measure_only=True;args.rubberband_fallback=False
                with process_lock(prior/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                season.ROOT=root;args.measure_only=False;args.rubberband_fallback=True
                # EP18's verified "lover" reading still comes from the original
                # disputed source set, separate from the latest timing feedback.
                args.source_evidence=n==18
                state.update(stage='editorial',updated_at=time.time());save_json(root/'season-progress.json',state)
                preceding.append(season.prepare(n,args,preceding))
                state['episodes'][str(n)]={'stage':'editorial_ready'}
                state.update(stage='rendering',updated_at=time.time());save_json(root/'season-progress.json',state)
                with process_lock(root/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                state['episodes'][str(n)]={'stage':'rendered_candidate'}
            except Exception as exc:
                state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                print('RESUME_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
            state['updated_at']=time.time();save_json(root/'season-progress.json',state)
        state['stage']='selected_candidates_complete' if all(
            e['stage']=='rendered_candidate' for e in state['episodes'].values()) else 'requires_review'
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
