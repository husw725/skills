"""One reviewed subtitle-meaning repair; never label it acoustic confirmation."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json
from repair_carmilla_measured import TIMING_ERRORS


def validate_basis(hints,rows):
    if set(hints)!={'4'}:raise ValueError('Only reviewed EP04 meaning normalization is authorized here')
    basis=hints['4']['source_basis'];cue=basis['original_cue']
    if (basis['kind']!='subtitle_semantic_normalization' or basis['audio_listened'] is not False
            or basis['speaker_verified'] is not False or cue['id']!='e04-16'
            or cue['text']!="i'll see you for tonight." or cue['start']!=101.233 or cue['end']!=102.766
            or basis['translation']!='Te vejo esta noite.'
            or next((r for r in rows if r['id']==cue['id']),None)!=cue):
        raise ValueError('Reviewed subtitle meaning/source scope changed')
    audit=basis['audit_report'];p=Path(audit['path'])
    if not p.is_file() or digest(p)!=audit['sha256']:raise ValueError('Independent meaning audit missing or changed')
    original=basis['original_subtitle'];p=Path(original['path'])
    if not p.is_file() or digest(p)!=original['sha256']:raise ValueError('Physical original subtitle changed')
    return basis


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg','editorial-hints'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--timing',action='store_true')
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business production runs on Windows')
    if any(not getattr(args,n).is_file() for n in ('codex_exe','mcp_config','ffmpeg','editorial_hints')):
        p.error('Existing executable/config/guidance required')
    root=season.SUBTITLE_TIMING_ROOT if args.timing else season.SUBTITLE_MEANING_ROOT
    root.mkdir(parents=True,exist_ok=True)
    args.prior_root=season.SUBTITLE_MEANING_ROOT if args.timing else season.FINAL_ROOT
    args.source_evidence=False;args.finalize_pending=True
    args.rubberband_fallback=True;args.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        state=read_json(root/'season-progress.json') if (root/'season-progress.json').exists() else {'episodes':{}}
        if any((r/'episode-04/render-report.json').exists() for r in season.paid_cache_roots()):
            raise ValueError('EP04 already rendered; reconcile publication rather than pay again')
        if args.timing:
            old=read_json(args.prior_root/'season-progress.json')['episodes']['4']
            if old.get('stage')!='requires_review' or old.get('detail') not in TIMING_ERRORS:
                raise ValueError('Only an inspected timing failure may enter measured repair')
        _,source,_=season.sources(4);basis=validate_basis(read_json(args.editorial_hints),read_json(source)['segments'])
        # The complete guidance, including this original cue and audit hash, is
        # bound into prepare's input fingerprint. Nothing rewrites the source.
        season.ROOT=root;state.update(stage='editorial',episode=4,started_at=time.time(),native_acceptance_passed=False)
        save_json(root/'season-progress.json',state)
        try:
            if args.timing:
                state['stage']='measuring';save_json(root/'season-progress.json',state)
                season.ROOT=args.prior_root;args.measure_only=True
                with process_lock(args.prior_root/'episode-04/render.lock',timeout=0):season.render(4,args)
                season.ROOT=root;args.measure_only=False;state['stage']='editorial'
                save_json(root/'season-progress.json',state)
            season.prepare(4,args,[])
            plan=read_json(root/'episode-04/plan.json')
            unit=next(u for u in plan['units'] if basis['original_cue']['id'] in u['cue_ids'])
            if unit['cue_ids']!=['e04-16'] or unit['translation']!=basis['translation']:
                raise ValueError('The reviewed subtitle normalization was not preserved')
            save_json(root/'episode-04/source-basis.json',basis)
            state.update(stage='rendering');save_json(root/'season-progress.json',state)
            with process_lock(root/'episode-04/render.lock',timeout=0):season.render(4,args)
            state['episodes']['4']={'stage':'rendered_candidate'};state['stage']='selected_candidates_complete'
        except Exception as exc:
            state['episodes']['4']={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
            state['stage']='requires_review'
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
