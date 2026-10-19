"""Resume EP27 with reviewed audio-backed editorial reconstruction, no new clone."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg','editorial-hints'):p.add_argument('--'+name,required=True,type=Path)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,n).is_file() for n in ('codex_exe','mcp_config','ffmpeg','editorial_hints')):p.error('Existing inputs required')
    root=season.RECONSTRUCTION_ROOT;root.mkdir(parents=True,exist_ok=True)
    args.prior_root=season.FINAL_ROOT;args.source_prior_root=season.RETRY_ROOT
    args.reconstruct_ep27=True;args.source_evidence=False;args.finalize_pending=True;args.rubberband_fallback=True
    args.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        if any((r/'episode-27/render-report.json').exists() for r in season.paid_cache_roots()):
            raise ValueError('EP27 already rendered; reconcile rather than regenerate')
        hints=read_json(args.editorial_hints)
        if set(hints)!={'27'}:raise ValueError('Unexpected reconstruction episode')
        approval=hints['27']['source_basis'];audit=approval['audit_report'];original=approval['original_subtitle']
        if (approval['kind']!='two_asr_editorial_reconstruction' or approval['audio_listened'] is not False
                or approval['speaker_verified'] is not False
                or set(approval['approved_translations'])!={'e27-1','e27-2','e27-11','e27-12'}
                or digest(Path(audit['path']))!=audit['sha256'] or digest(Path(original['path']))!=original['sha256']):
            raise ValueError('Reviewed reconstruction basis changed')
        season.ROOT=root;state={'stage':'editorial','episode':27,'episodes':{},'started_at':time.time(),'native_acceptance_passed':False}
        save_json(root/'season-progress.json',state)
        try:
            season.prepare(27,args,[])
            reviewed=read_json(root/'episode-27/reviewed.json');by={c['id']:c for c in reviewed['cues']}
            for cue,text in approval['approved_translations'].items():
                if by[cue]['translation']!=text:raise ValueError('Independently reviewed source meaning was not retained')
            state['stage']='rendering';save_json(root/'season-progress.json',state)
            with process_lock(root/'episode-27/render.lock',timeout=0):season.render(27,args)
            state.update(stage='selected_candidates_complete',episodes={'27':{'stage':'rendered_candidate'}})
        except Exception as exc:
            state.update(stage='requires_review',episodes={'27':{'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}})
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
