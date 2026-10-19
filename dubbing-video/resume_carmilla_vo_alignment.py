"""Reuse the reviewed EP05 plan/audio, placing an inner voiceover in its adjacent production gap."""
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
    prior=season.SPEECH2_ROOT;root=season.VO_ALIGNMENT_ROOT
    with process_lock(season.BASE_ROOT/'season.lock',timeout=14400):
        if any((r/'episode-05/render-report.json').exists() for r in season.paid_cache_roots()):
            raise ValueError('EP05 already rendered; reconcile instead of generating')
        old=read_json(prior/'season-progress.json')['episodes']['5']
        if old.get('stage')!='requires_review' or old.get('detail') not in TIMING_ERRORS:
            raise ValueError('An inspected timing failure is required')
        basis=read_json(a.basis);audit=basis['audit_report']
        if digest(Path(audit['path']))!=audit['sha256']:raise ValueError('Independent boundary audit changed')
        src=prior/'episode-05';plan=read_json(src/'plan.json');season.validate_reviewed_plan(src,plan)
        if digest(src/'plan.json')!=basis['plan_sha256']:raise ValueError('Reviewed plan changed')
        root.mkdir(parents=True,exist_ok=True);dst=root/'episode-05';dst.mkdir(exist_ok=True)
        names=['plan.json','reviewed.json','reviewed-plan-fingerprint.json','screenplay-context.json',
               'translation.json','Carmilla_EP05_pt-BR_revised.srt','editorial-input.json']
        for name in names:
            if (dst/name).exists() and digest(dst/name)!=digest(src/name):raise ValueError('New-root editorial copy differs')
            if not (dst/name).exists():shutil.copyfile(src/name,dst/name)
        season.bind(dst/'audio-boundary-basis.json',basis)
        full_basis=dst/'audio-boundary-basis.private.json'
        if full_basis.exists() and read_json(full_basis)!=basis:raise ValueError('Full alignment basis changed')
        if not full_basis.exists():save_json(full_basis,basis)
        a.prior_root=prior;a.cache_roots=[r for r in season.paid_cache_roots() if r!=root]
        from carmilla_ep05_alignment import verify_basis
        verify_basis(dst,plan)
        a.finalize_pending=True;a.rubberband_fallback=True;a.ep05_vo_alignment=True
        season.ROOT=root;state={'stage':'rendering','episode':5,'episodes':{},'started_at':time.time(),'native_acceptance_passed':False}
        save_json(root/'season-progress.json',state)
        try:
            with process_lock(dst/'render.lock',timeout=0):season.render(5,a)
            state.update(stage='selected_candidates_complete',episodes={'5':{'stage':'rendered_candidate'}})
        except Exception as exc:
            state.update(stage='requires_review',episodes={'5':{'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}})
        state['finished_at']=time.time();save_json(root/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
