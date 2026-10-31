"""Verify an actual completed episode for candidate delivery; no native-listening claim."""
import argparse
from pathlib import Path
import sys
from dub_episode import digest,run
from translate import read_json,save_json
from process_lock import process_lock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--ffmpeg',type=Path,required=True)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows media candidate verification only')
    root=args.root
    with process_lock(root/'delivery-check.lock',timeout=0):
        report_path=root/'render-report.private.json';report=read_json(report_path)
        plan_path=root/'speech-plan.private.json';plan=read_json(plan_path);fit_path=root/'fit-report.private.json';fit=read_json(fit_path)
        if (plan['holds'] or not report['picture_payload_identical'] or report['plan_sha256']!=digest(plan_path)
            or report['fit_report_sha256']!=digest(fit_path) or fit['blocked'] or len(fit['groups'])!=len(plan['groups'])
            or digest(report['output'])!=report['output_sha256'] or digest(report['subtitle'])!=report['subtitle_sha256']):
            raise ValueError('Actual completed episode/coverage differs')
        for path,sha in plan['inputs_sha256'].items():
            if digest(path)!=sha:raise ValueError('Source changed after production')
        for row,group in zip(fit['groups'],plan['groups']):
            if row['id']!=group['id'] or digest(row['path'])!=row['sha256'] or row['post_atempo']>1.2+1e-8:
                raise ValueError('Actual fitted audio changed')
        if Path(report['subtitle']).read_text(encoding='utf-8')!=plan['subtitle_text']:
            raise ValueError('Subtitle differs from frozen production words')
        run([args.ffmpeg,'-nostdin','-v','error','-xerror','-i',report['output'],'-f','null','-'])
        hashes=[run([args.ffmpeg,'-nostdin','-v','error','-i',p,'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip() for p in (plan['media']['video'],report['output'])]
        if hashes[0]!=hashes[1]:raise ValueError('Original picture payload differs')
        audit={'mode':'automated_actual_media_checks','project_id':plan['project_id'],'episode':plan['episode'],
               'render_report_sha256':digest(report_path),'plan_sha256':digest(plan_path),'fit_report_sha256':digest(fit_path),
               'video_sha256':report['output_sha256'],'subtitle_sha256':report['subtitle_sha256'],
               'full_decode_passed':True,'picture_payload_identical':True,'all_planned_groups_fitted':True,
               'native_listening_passed':False,'source_speaker_verified':False,'background_purity_verified':False}
        audit_path=root/'technical-delivery-check.private.json'
        if audit_path.exists() and read_json(audit_path)!=audit:raise ValueError('Prior technical evidence changed')
        if not audit_path.exists():save_json(audit_path,audit)
        approval={'project_id':plan['project_id'],'episode':plan['episode'],'technical_media_approved':True,
                  'native_listening_passed':False,'render_report_sha256':digest(report_path),
                  'video_sha256':report['output_sha256'],'subtitle_sha256':report['subtitle_sha256'],
                  'audit_report_path':str(audit_path),'audit_report_sha256':digest(audit_path)}
        approval_path=root/'publication-approval.private.json'
        if approval_path.exists() and read_json(approval_path)!=approval:raise ValueError('Prior delivery approval changed')
        if not approval_path.exists():save_json(approval_path,approval)
        print('TECHNICAL_CANDIDATE_DELIVERY_READY',plan['project_id'],plan['episode'])


if __name__=='__main__':main()
