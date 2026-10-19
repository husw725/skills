"""Reconcile only failed publication checks after a complete season publication pass."""
import argparse,sys,time
from pathlib import Path
from publish_season_candidates import candidates,publish,PUBLICATION
from notify_season_complete import verify_delivery
from publish_review import materials
from mflix_client import Mflix
from process_lock import process_lock
from rerun_carmilla_season import validate_reviewed_plan
from dub_episode import digest
from translate import read_json,save_json,fingerprint


def retained_delivery(n,folder,result,receipt,candidate_marker):
    plan=read_json(folder/'plan.json');validate_reviewed_plan(folder,plan)
    report=read_json(folder/'render-report.json')
    expected={'folder':str(folder),'video_sha256':result['video_sha256'],'subtitle_sha256':result['subtitle_sha256'],'plan_sha256':digest(folder/'plan.json')}
    if read_json(candidate_marker).get('fingerprint')!=fingerprint(expected):
        raise ValueError('Original publication candidate binding changed')
    if (result!=receipt or result.get('episode')!=n or plan['episode']!=n or plan['project_id']!=59
            or report['output_sha256']!=result['video_sha256'] or plan['blocking_issues']
            or report['episode']!=n or report['status']!='rendered_season_revision_candidate'
            or not report['video_payload_identical'] or report['source_audio_in_output'] or report['new_clone_count']!=0
            or digest(folder/'reviewed.json')!=plan['reviewed_response_sha256']
            or digest(folder/'screenplay-context.json')!=plan['reviewed_context_sha256']
            or result['subtitle_sha256']!=digest(folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt')
            or result['subtitle_sha256']!=plan['translation_srt_sha256']):
        raise ValueError('Prior successful delivery changed; inspect instead of merging status')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('s3-config','mcp-config','ffmpeg'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--wait-for-lock',type=int,default=14400);a=p.parse_args()
    if sys.platform!='win32':p.error('Business publication stays on Windows')
    if not 0<=a.wait_for_lock<=14400:p.error('Bounded publication wait required')
    with process_lock(PUBLICATION/'season-publication.lock',timeout=a.wait_for_lock):
        available=candidates()
        if set(available)!=set(range(1,33)):raise ValueError('All 32 actual candidates required before publication reconciliation')
        status=read_json(PUBLICATION/'progress.json');published=status['published'];failures=status['requires_review']
        if set(published)|set(failures)!={str(n) for n in range(1,33)} or set(published)&set(failures):
            raise ValueError('A complete prior publication pass is required')
        for key,result in published.items():
            n=int(key);folder=available[n];receipt=read_json(PUBLICATION/f'episode-{n:02}'/result['video_sha256']/'publication-result.json')
            retained_delivery(n,folder,result,receipt,PUBLICATION/f'episode-{n:02}'/result['video_sha256']/'candidate.json')
        for key in sorted(list(failures),key=int):
            n=int(key)
            try:published[key]=publish(n,available[n],a)
            except Exception as exc:failures[key]={'type':type(exc).__name__,'detail':str(exc)}
            else:del failures[key]
            save_json(PUBLICATION/'progress.json',status)
        status['all_32_published']=set(published)=={str(n) for n in range(1,33)} and not failures
        if status['all_32_published']:
            # Strong external readback before a completion status is persisted.
            verify_delivery(status,materials(Mflix(a.mcp_config),148))
        status['reconciled_at']=time.time();save_json(PUBLICATION/'progress.json',status)
        print('PUBLICATION_RECONCILED',len(published),len(failures),flush=True)
        if not status['all_32_published']:raise SystemExit(2)


if __name__=='__main__':main()
