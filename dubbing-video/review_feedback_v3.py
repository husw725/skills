"""Publish the verified EP02 feedback candidate as Review v3, preserving v1/v2."""
import argparse
from pathlib import Path
import sys
from dub_episode import digest, safe_submit
from mflix_client import Mflix
from process_lock import process_lock
from translate import read_json, save_json, fingerprint


def history(client):
    data = client.call('getReviewMaterialHistory', {'projectId': 148, 'gateType': 'FINAL_CUT', 'assetId': 2478})
    if not isinstance(data, list):
        raise ValueError('Expected Review version list')
    for row in data:
        if row['projectId'] != 148 or row['gateType'] != 'FINAL_CUT' or row['name'] != 'Carmilla | EP.02 | pt-BR':
            raise ValueError('Unexpected Review material scope')
    return data


def publish(config):
    root = Path('output/drama-01/episode-02/feedback-v3')
    report = read_json(root/'render-report.json')
    video = root/'Carmilla_EP02_pt-BR_feedback_v3.mp4'
    if report['episode'] != 2 or report['status'] != 'rendered_feedback_candidate' or not report['video_payload_identical']:
        raise ValueError('Unverified pilot output')
    if digest(video) != report['output_sha256']:
        raise ValueError('Final video SHA changed')
    folder = Path('output/review-publication/148/Carmilla/feedback-ep02-v3')
    folder.mkdir(parents=True, exist_ok=True)
    with process_lock(folder/'publish.lock', timeout=0):
        client = Mflix(config)
        versions = history(client)
        save_json(folder/'history-before.private.json', versions)
        upload_record = folder/'upload.private.json'
        if upload_record.exists():
            uploaded = read_json(upload_record)
            if uploaded['sha256'] != report['output_sha256']:
                raise ValueError('Review upload receipt differs from final video')
        else:
            url = client.upload(video)
            response = client.http.get(url, timeout=180)
            if response.status_code != 200:
                raise ValueError('Uploaded video cannot be read back')
            import hashlib
            if hashlib.sha256(response.content).hexdigest() != report['output_sha256']:
                raise ValueError('Uploaded video SHA mismatch')
            uploaded = {'url': url, 'sha256': report['output_sha256']}
            save_json(upload_record, uploaded)
        existing = [v for v in versions if v.get('url') == uploaded['url']]
        if existing:
            if len(existing) != 1 or existing[0]['version'] != 3:
                raise ValueError('Uploaded URL unexpectedly registered')
            receipt = existing[0]
        else:
            if {(v['assetId'], v['version']) for v in versions} != {(2354, 1), (2478, 2)}:
                raise ValueError('Review already has another version; do not append v4')
            notes = ('Feedback repair candidate: only two Laura cries near 49.4s/55s replaced. '
                     'Reuse existing MiniMax Laura, fearful + IPA synthesis control; no new clone. '
                     'Other 15 Cartesia v2 groups retained byte-for-byte; original subtitles/video unchanged. '
                     'Hybrid-model/timbre continuity, nasal pronunciation and fear/scream require native review. '
                     'IPA parsing and emotional quality NOT verified by assistant. '
                     'Comments 7488/7489 have no timestamps; these are candidate locations. '
                     f'SHA256: {report["output_sha256"]}')
            material = {k: None for k in ('artDirectionSubMaterials', 'category', 'createdAt', 'documentKind',
                        'parentAssetId', 'status', 'updatedAt', 'version')}
            material.update({'assetId': 2478, 'projectId': 148, 'gateType': 'FINAL_CUT',
                             'name': next(v for v in versions if v['assetId'] == 2478)['name'], 'url': uploaded['url'],
                             'durationSeconds': round(report['duration_seconds']),
                             'tags': sorted(set(next(v for v in versions if v['assetId'] == 2478).get('tags') or []) | {'Carmilla', 'pt-BR', 'Cartesia', 'MiniMax'}),
                             'note': notes})
            signature = fingerprint(material)
            sig_file = folder/'request-fingerprint.json'
            if sig_file.exists() and read_json(sig_file)['fingerprint'] != signature:
                raise ValueError('Review version request changed')
            save_json(sig_file, {'fingerprint': signature})
            # Mutation is submitted once; if connection is uncertain, query history before any retry.
            receipt = safe_submit(client, 'updateReviewMaterialVersion', {'material': material},
                                  folder/'version-submission.private.json')
        versions = history(client)
        save_json(folder/'history-after.private.json', versions)
        new = [v for v in versions if v.get('url') == uploaded['url'] and v.get('version') == 3]
        old = [v for v in versions if v.get('assetId') == 2478 and v.get('version') == 2]
        v1 = [v for v in versions if v.get('assetId') == 2354 and v.get('version') == 1]
        if len(new) != 1 or len(old) != 1 or len(v1) != 1 or new[0]['assetId'] in (2354, 2478):
            raise ValueError('Review version-chain readback failed')
        summary = {'status': 'uploaded_review_v3', 'project_id': 148,
                   'old_asset_id': 2478, 'asset_id': new[0]['assetId'], 'version': 3,
                   'url': uploaded['url'], 'sha256': report['output_sha256'],
                   'old_version_retained': True, 'native_ptBR_listening_reviewed': False}
        save_json(folder/'publication-result.json', summary)
        print('REVIEW_V3', summary['asset_id'], uploaded['url'], flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mcp-config', required=True, type=Path)
    args = p.parse_args()
    if sys.platform != 'win32':
        p.error('Business execution is Windows-only')
    publish(args.mcp_config)


if __name__ == '__main__':
    main()
