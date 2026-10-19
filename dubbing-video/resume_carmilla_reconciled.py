"""Resume EP05 with independently reviewed name/idiom normalization, no new clone."""
import argparse
from pathlib import Path
import sys,time

import rerun_carmilla_season as season
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json
from repair_carmilla_measured import TIMING_ERRORS


SPEECH_TRANSLATIONS = {
    'e05-23': 'O sangue da minha filha é especial,',
    'e05-16': 'pode purificar trevas.',
    'e05-17': 'Senti assim que ela nasceu.',
    'e05-18': 'Devia temê-la, tudo em mim grita pra fugir,',
    'e05-19': 'mas não consigo odiá-la, me sinto segura.',
}


def validate_retained_editorial(reviewed, prior, changes=None):
    expected = [(c['id'], (changes or {}).get(c['id'], c['translation']), c['emotion']) for c in prior['cues']]
    actual = [(c['id'], c['translation'], c['emotion']) for c in reviewed['cues']]
    if reviewed['groups'] != prior['groups'] or actual != expected:
        raise ValueError('Only independently approved text changes may differ; retain all groups/directions')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('codex-exe','mcp-config','ffmpeg','editorial-hints'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--editorial-repair',action='store_true')
    p.add_argument('--timing-repair',action='store_true')
    p.add_argument('--paragraph-repair',action='store_true')
    p.add_argument('--diary-production',action='store_true')
    p.add_argument('--speech-repair',action='store_true')
    args=p.parse_args()
    if sum([args.editorial_repair,args.timing_repair,args.paragraph_repair,args.diary_production,args.speech_repair])>1:p.error('Choose one versioned repair stage')
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    if any(not getattr(args,n).is_file() for n in ('codex_exe','mcp_config','ffmpeg','editorial_hints')):p.error('Existing inputs required')
    root=season.SPEECH_ROOT if args.speech_repair else season.DIARY_ROOT if args.diary_production else season.PARAGRAPH_ROOT if args.paragraph_repair else (season.RECONCILED_TIMING_ROOT if args.timing_repair else (season.RECONCILED2_ROOT if args.editorial_repair else season.RECONCILED_ROOT));root.mkdir(parents=True,exist_ok=True)
    args.prior_root=season.DIARY_ROOT if args.speech_repair else season.RECONCILED2_ROOT if args.timing_repair or args.paragraph_repair or args.diary_production else season.FINAL_ROOT;args.source_prior_root=season.RETRY_ROOT
    args.reconcile_ep05=True;args.ep05_paragraph=args.paragraph_repair or args.diary_production or args.speech_repair;args.ep05_diary=args.diary_production or args.speech_repair;args.source_evidence=False;args.finalize_pending=True;args.rubberband_fallback=True
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
        if args.timing_repair or args.paragraph_repair or args.diary_production or args.speech_repair:
            old=read_json(args.prior_root/'season-progress.json')['episodes']['5']
            if old.get('detail') not in TIMING_ERRORS:raise ValueError('Only inspected timing errors may be repaired')
        if args.paragraph_repair or args.diary_production or args.speech_repair:
            measured=read_json(args.prior_root/'episode-05/duration-measurements.json')
            if measured.get('complete') is not True or measured['plan_sha256']!=digest(args.prior_root/'episode-05/plan.json'):
                raise ValueError('Complete measurements for the exact reviewed plan are required')
            superseded=read_json(season.RECONCILED_TIMING_ROOT/'season-progress.json')
            if superseded.get('stage')!='superseded_before_tts' or (season.RECONCILED_TIMING_ROOT/'episode-05/plan.json').exists():
                raise ValueError('Obsolete editorial worker must be safely superseded before this version')
            if any((season.RECONCILED_TIMING_ROOT/'episode-05').glob('utterances/*/request-fingerprint.json')):
                raise ValueError('Unexpected paid request in superseded editorial version')
        if args.diary_production:
            prior=read_json(season.PARAGRAPH_ROOT/'season-progress.json')['episodes']['5']
            if prior.get('detail')!='Unknown readers cannot be inferred identical from voice casting':
                raise ValueError('Only the inspected diary grouping failure may use this version')
            if (season.PARAGRAPH_ROOT/'episode-05/plan.json').exists() or any((season.PARAGRAPH_ROOT/'episode-05').glob('utterances/*/request-fingerprint.json')):
                raise ValueError('Unexpected renderable/paid prior diary grouping version')
        hints=read_json(args.editorial_hints)
        if set(hints)!={'5'}:raise ValueError('Unexpected reconstruction episode')
        approval=hints['5']['source_basis'];audit=approval['audit_report'];original=approval['original_subtitle']
        if args.diary_production or args.speech_repair:
            reference=hints['5']['existing_reviewed_candidate']
            prior_review=(season.DIARY_ROOT if args.speech_repair else season.PARAGRAPH_ROOT)/'episode-05/reviewed.json'
            if (Path(reference['path'])!=prior_review or digest(prior_review)!=reference['sha256']
                    or read_json(prior_review)!=reference['data']):raise ValueError('Independently reviewed editorial reference changed')
            if args.speech_repair and hints['5'].get('approved_timing_translation_changes') != SPEECH_TRANSLATIONS:
                raise ValueError('Only five independently approved timing translations may change')
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
            if args.diary_production or args.speech_repair:
                validate_retained_editorial(reviewed, reference['data'], SPEECH_TRANSLATIONS if args.speech_repair else None)
            if args.paragraph_repair or args.diary_production or args.speech_repair:
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
