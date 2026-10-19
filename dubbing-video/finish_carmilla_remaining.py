"""One targeted repair of the four remaining measured failures, preserving evidence."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from process_lock import process_lock
from repair_carmilla_measured import TIMING_ERRORS
from translate import read_json,save_json

PRIORS={10:season.RESUME_ROOT,12:season.SOURCE_RESUME_ROOT,18:season.RESUME_ROOT,32:season.RESUME_ROOT}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg','editorial-hints'):p.add_argument('--'+name,required=True,type=Path)
    scope=p.add_mutually_exclusive_group()
    scope.add_argument('--ep10-continuity',action='store_true')
    scope.add_argument('--ep12-continuity',action='store_true')
    scope.add_argument('--ep20-timing',action='store_true')
    scope.add_argument('--ep20-pause',action='store_true')
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,name).is_file() for name in ('codex_exe','mcp_config','ffmpeg','editorial_hints')):
        p.error('Existing executables, private config and targeted guidance required')
    if args.ep10_continuity:root=season.FINISH2_ROOT;priors={10:season.FINISH_ROOT}
    elif args.ep12_continuity:root=season.FINISH12_ROOT;priors={12:season.FINISH_ROOT}
    elif args.ep20_timing:root=season.NEIGHBOR_TIMING_ROOT;priors={20:season.NEIGHBOR2_ROOT}
    elif args.ep20_pause:root=season.NEIGHBOR_PAUSE_ROOT;priors={20:season.NEIGHBOR_TIMING_ROOT}
    else:root=season.FINISH_ROOT;priors=PRIORS
    root.mkdir(parents=True,exist_ok=True)
    args.finalize_pending=True;args.rubberband_fallback=True
    args.source_prior_root=season.RETRY_ROOT
    args.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        state=read_json(root/'season-progress.json') if (root/'season-progress.json').exists() else {'episodes':{}}
        episodes=[]
        for n,prior in priors.items():
            if state['episodes'].get(str(n),{}).get('stage')=='rendered_candidate':continue
            if any((r/f'episode-{n:02}'/'render-report.json').exists() for r in args.cache_roots):continue
            old=read_json(prior/'season-progress.json')['episodes'][str(n)]
            if old.get('stage')=='requires_review' and old.get('detail') in TIMING_ERRORS:episodes.append(n)
        state.update(started_at=time.time(),selected_episodes=episodes,native_acceptance_passed=False)
        preceding=[]
        for n in episodes:
            try:
                prior=priors[n];args.prior_root=prior;season.ROOT=prior;args.measure_only=True
                args.ep20_pause_fit=args.ep20_pause;args.ep20_pause=False
                state.update(stage='measuring',episode=n,updated_at=time.time());save_json(root/'season-progress.json',state)
                with process_lock(prior/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                season.ROOT=root;args.measure_only=False;args.ep20_pause=args.ep20_pause_fit
                args.source_evidence=n in (12,18,20)
                args.source_evidence_mode='tight' if n==12 else ('raw-neighbor' if n==20 else 'context')
                state.update(stage='editorial',updated_at=time.time());save_json(root/'season-progress.json',state)
                preceding.append(season.prepare(n,args,preceding))
                state['episodes'][str(n)]={'stage':'editorial_ready'}
                state.update(stage='rendering',updated_at=time.time());save_json(root/'season-progress.json',state)
                with process_lock(root/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                state['episodes'][str(n)]={'stage':'rendered_candidate'}
            except Exception as exc:
                state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                print('FINAL_TARGETED_REPAIR_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
            state['updated_at']=time.time();save_json(root/'season-progress.json',state)
        state.update(stage='selected_candidates_complete' if all(e['stage']=='rendered_candidate'
            for e in state['episodes'].values()) else 'requires_review',finished_at=time.time())
        save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
