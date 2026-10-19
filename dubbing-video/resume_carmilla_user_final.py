"""Complete the two episodes after the user's explicit final-storyboard decision."""
import argparse
from pathlib import Path
import sys,time
import rerun_carmilla_season as season
from carmilla_final_authority import SPECS
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg','editorial-hints'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--stage',choices=['editorial','all'],default='all')
    a=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(a,k).is_file() for k in ('codex_exe','mcp_config','ffmpeg','editorial_hints')):p.error('Existing inputs required')
    root=season.STORYBOARD_FINAL_ROOT;root.mkdir(parents=True,exist_ok=True)
    a.prior_root=season.FINAL_ROOT;a.source_prior_root=season.RETRY_ROOT
    a.final_authorized_source=True;a.source_evidence=False;a.finalize_pending=True;a.rubberband_fallback=True
    a.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
    hints=read_json(a.editorial_hints)
    if set(hints)!={'8','29'}:raise ValueError('Only the two user-resolved episodes may use this stage')
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        state=read_json(root/'season-progress.json') if (root/'season-progress.json').exists() else {'episodes':{}}
        state.update(started_at=time.time(),native_acceptance_passed=False)
        for n in (8,29):
            if (root/f'episode-{n:02}/render-report.json').exists():continue
            if any((r/f'episode-{n:02}/render-report.json').exists() for r in a.cache_roots):
                raise ValueError('Episode already rendered in another attempt; reconcile rather than regenerate')
            season.ROOT=root
            try:
                state.update(stage='editorial',episode=n);save_json(root/'season-progress.json',state)
                season.prepare(n,a,[])
                folder=root/f'episode-{n:02}';plan=read_json(folder/'plan.json');reviewed=read_json(folder/'reviewed.json')
                by={c['id']:c for c in reviewed['cues']}
                for cue,spec in SPECS[n].items():
                    if by[cue]['translation']!=spec[-1]:raise ValueError('User-resolved source meaning/approved translation changed')
                if plan['blocking_issues']:raise ValueError('Unresolved source issue remains')
                state['episodes'][str(n)]={'stage':'editorial_ready'}
                if a.stage=='all':
                    state['stage']='rendering';save_json(root/'season-progress.json',state)
                    with process_lock(folder/'render.lock',timeout=0):season.render(n,a)
                    state['episodes'][str(n)]={'stage':'rendered_candidate'}
            except Exception as exc:
                state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
            save_json(root/'season-progress.json',state)
        expected='editorial_ready' if a.stage=='editorial' else 'rendered_candidate'
        state['stage']='selected_candidates_complete' if all(state['episodes'].get(str(n),{}).get('stage') in (expected,'rendered_candidate') for n in (8,29)) else 'requires_review'
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
