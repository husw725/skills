"""Resume disputed episodes from one complete, independently bound tight ASR pair."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from process_lock import process_lock
from translate import read_json,save_json

EPISODES=(6,12)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg'):p.add_argument('--'+name,required=True,type=Path)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,name).is_file() for name in ('codex_exe','mcp_config','ffmpeg')):p.error('Existing executable/config required')
    if read_json('output/carmilla-source-tight-20261017/progress.json')['stage']!='evidence_ready':
        p.error('Complete source evidence first')
    root=season.SOURCE_RESUME_ROOT;root.mkdir(parents=True,exist_ok=True)
    args.prior_root=season.FINAL_ROOT;args.source_prior_root=season.RETRY_ROOT
    args.source_evidence=True;args.source_evidence_mode='tight';args.finalize_pending=True
    args.rubberband_fallback=True;args.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        state=read_json(root/'season-progress.json') if (root/'season-progress.json').exists() else {'episodes':{}}
        state.update(started_at=time.time(),native_acceptance_passed=False)
        preceding=[];season.ROOT=root
        for n in EPISODES:
            if state['episodes'].get(str(n),{}).get('stage')=='rendered_candidate':continue
            # These two independently corroborated episodes have no delivered season candidate.
            if any((r/f'episode-{n:02}'/'render-report.json').exists() for r in args.cache_roots):
                raise ValueError('A source episode already has a candidate; inspect rather than regenerate')
            try:
                state.update(stage='editorial',episode=n,updated_at=time.time());save_json(root/'season-progress.json',state)
                preceding.append(season.prepare(n,args,preceding))
                state['episodes'][str(n)]={'stage':'editorial_ready'}
                state.update(stage='rendering',updated_at=time.time());save_json(root/'season-progress.json',state)
                with process_lock(root/f'episode-{n:02}'/'render.lock',timeout=0):season.render(n,args)
                state['episodes'][str(n)]={'stage':'rendered_candidate'}
            except Exception as exc:
                state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                print('SOURCE_RESUME_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
            state['updated_at']=time.time();save_json(root/'season-progress.json',state)
        state.update(stage='selected_candidates_complete' if all(e['stage']=='rendered_candidate'
            for e in state['episodes'].values()) else 'requires_review',finished_at=time.time())
        save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
