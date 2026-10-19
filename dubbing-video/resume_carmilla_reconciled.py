"""Resume EP05 with independently reviewed name/idiom normalization, no new clone."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json
from repair_carmilla_measured import TIMING_ERRORS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg','editorial-hints'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--editorial-repair',action='store_true')
    p.add_argument('--timing-repair',action='store_true')
    p.add_argument('--paragraph-repair',action='store_true')
    args=p.parse_args()
    if sum([args.editorial_repair,args.timing_repair,args.paragraph_repair])>1:p.error('Choose one versioned repair stage')
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,n).is_file() for n in ('codex_exe','mcp_config','ffmpeg','editorial_hints')):p.error('Existing inputs required')
    root=season.PARAGRAPH_ROOT if args.paragraph_repair else (season.RECONCILED_TIMING_ROOT if args.timing_repair else (season.RECONCILED2_ROOT if args.editorial_repair else season.RECONCILED_ROOT));root.mkdir(parents=True,exist_ok=True)
    args.prior_root=season.RECONCILED2_ROOT if args.timing_repair or args.paragraph_repair else season.FINAL_ROOT;args.source_prior_root=season.RETRY_ROOT
    args.reconcile_ep05=True;args.ep05_paragraph=args.paragraph_repair;args.source_evidence=False;args.finalize_pending=True;args.rubberband_fallback=True
    args.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        if any((r/'episode-05/render-report.json').exists() for r in season.paid_cache_roots()):
            raise ValueError('EP05 already rendered; reconcile rather than regenerate')
        if args.editorial_repair:
            old=read_json(season.RECONCILED_ROOT/'season-progress.json')['episodes']['5']
            if old.get('detail')!='Unsupported source reading without audio evidence':
                raise ValueError('Only the inspected editorial field-contract failure may use this repair')
            if any((season.RECONCILED_ROOT/'episode-05').glob('utterances/*/request-fingerprint.json')):
                raise ValueError('Prior editorial version unexpectedly has paid requests')
        if args.timing_repair or args.paragraph_repair:
            old=read_json(args.prior_root/'season-progress.json')['episodes']['5']
            if old.get('detail') not in TIMING_ERRORS:raise ValueError('Only inspected timing errors may be repaired')
        if args.paragraph_repair:
            measured=read_json(args.prior_root/'episode-05/duration-measurements.json')
            if measured.get('complete') is not True or measured['plan_sha256']!=digest(args.prior_root/'episode-05/plan.json'):
                raise ValueError('Complete measurements for the exact reviewed plan are required')
            superseded=read_json(season.RECONCILED_TIMING_ROOT/'season-progress.json')
            if superseded.get('stage')!='superseded_before_tts' or (season.RECONCILED_TIMING_ROOT/'episode-05/plan.json').exists():
                raise ValueError('Obsolete editorial worker must be safely superseded before this version')
            if any((season.RECONCILED_TIMING_ROOT/'episode-05').glob('utterances/*/request-fingerprint.json')):
                raise ValueError('Unexpected paid request in superseded editorial version')
        hints=read_json(args.editorial_hints)
        if set(hints)!={'5'}:raise ValueError('Unexpected reconstruction episode')
        approval=hints['5']['source_basis'];audit=approval['audit_report'];original=approval['original_subtitle']
        if (approval['kind']!='editorial_name_and_subtitle_normalization' or approval['audio_listened'] is not False
                or approval['speaker_verified'] is not False
                or set(approval['approved_translations'])!={'e05-7','e05-26','e05-35','e05-36'}
                or digest(Path(audit['path']))!=audit['sha256'] or digest(Path(original['path']))!=original['sha256']):
            raise ValueError('Reviewed reconstruction basis changed')
        season.ROOT=root;state={'stage':'editorial','episode':5,'episodes':{},'started_at':time.time(),'native_acceptance_passed':False}
        save_json(root/'season-progress.json',state)
        try:
            if args.timing_repair:
                season.ROOT=args.prior_root;args.measure_only=True
                state['stage']='measuring';save_json(root/'season-progress.json',state)
                with process_lock(args.prior_root/'episode-05/render.lock',timeout=0):season.render(5,args)
                season.ROOT=root;args.measure_only=False
                state['stage']='editorial';save_json(root/'season-progress.json',state)
            season.prepare(5,args,[])
            reviewed=read_json(root/'episode-05/reviewed.json');by={c['id']:c for c in reviewed['cues']}
            for cue,text in approval['approved_translations'].items():
                if by[cue]['translation']!=text:raise ValueError('Independently reviewed source meaning was not retained')
            if args.paragraph_repair:
                plan=read_json(root/'episode-05/plan.json')
                unit=next(u for u in plan['units'] if 'e05-18' in u['cue_ids'])
                if (unit['cue_ids']!=['e05-18','e05-19'] or unit['production_voice']!='Laura'
                        or unit['start']!=68.866 or unit['end']!=74.4
                        or any(by[c]['emotion']!='surprised' for c in unit['cue_ids'])):
                    raise ValueError('Reviewed EP05 thought/casting/performance direction changed')
            state['stage']='rendering';save_json(root/'season-progress.json',state)
            with process_lock(root/'episode-05/render.lock',timeout=0):season.render(5,args)
            state.update(stage='selected_candidates_complete',episodes={'5':{'stage':'rendered_candidate'}})
        except Exception as exc:
            state.update(stage='requires_review',episodes={'5':{'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}})
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
