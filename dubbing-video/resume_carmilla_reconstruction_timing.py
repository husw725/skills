"""Reuse the reviewed EP27 plan/audio, fitting its complete sentence to an evidenced tail."""
import argparse,shutil,sys,time
from pathlib import Path
import rerun_carmilla_season as season
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json
from repair_carmilla_measured import TIMING_ERRORS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('mcp-config','ffmpeg','basis'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args()
    if sys.platform!='win32':p.error('Business execution stays on Windows')
    prior=season.RECONSTRUCTION_ROOT;root=season.RECONSTRUCTION_TIMING_ROOT
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        if any((r/'episode-27/render-report.json').exists() for r in season.paid_cache_roots()):
            raise ValueError('EP27 already rendered; reconcile instead of generating')
        old=read_json(prior/'season-progress.json')['episodes']['27']
        if old.get('stage')!='requires_review' or old.get('detail') not in TIMING_ERRORS:
            raise ValueError('An inspected timing failure is required')
        basis=read_json(a.basis);audit=basis['audit_report']
        if digest(Path(audit['path']))!=audit['sha256']:raise ValueError('Independent boundary audit changed')
        src=prior/'episode-27';plan=read_json(src/'plan.json');season.validate_reviewed_plan(src,plan)
        if digest(src/'plan.json')!=basis['plan_sha256']:raise ValueError('Reviewed plan changed')
        unit=plan['units'][15]
        if unit['cue_ids']!=['e27-1','e27-2'] or plan['units'][16]['cue_ids']!=['e27-3'] or plan['units'][16]['start']!=76.366:
            raise ValueError('Precise current and next source groups required')
        season.post_gap_seconds(27,unit,ep27_boundary=True)
        wav=src/'utterances'/unit['id']/'original.wav'
        if digest(wav)!=basis['audio_sha256']:raise ValueError('Paid source audio changed')
        root.mkdir(parents=True,exist_ok=True);dst=root/'episode-27';dst.mkdir(exist_ok=True)
        names=['plan.json','reviewed.json','reviewed-plan-fingerprint.json','screenplay-context.json',
               'translation.json','Carmilla_EP27_pt-BR_revised.srt','editorial-input.json']
        for name in names:
            if (dst/name).exists() and digest(dst/name)!=digest(src/name):raise ValueError('New-root editorial copy differs')
            if not (dst/name).exists():shutil.copyfile(src/name,dst/name)
        season.bind(dst/'audio-boundary-basis.json',basis)
        a.prior_root=prior;a.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
        a.finalize_pending=True;a.rubberband_fallback=True;a.ep27_boundary=True
        season.ROOT=root;state={'stage':'rendering','episode':27,'episodes':{},'started_at':time.time(),'native_acceptance_passed':False}
        save_json(root/'season-progress.json',state)
        try:
            with process_lock(dst/'render.lock',timeout=0):season.render(27,a)
            state.update(stage='selected_candidates_complete',episodes={'27':{'stage':'rendered_candidate'}})
        except Exception as exc:
            state.update(stage='requires_review',episodes={'27':{'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}})
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
