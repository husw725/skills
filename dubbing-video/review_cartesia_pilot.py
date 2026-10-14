"""Publish only the verified Carmilla EP02 Cartesia pilot as its Review v2."""
import argparse
from pathlib import Path
import sys
from dub_episode import digest, safe_submit
from mflix_client import Mflix
from process_lock import process_lock
from translate import read_json, save_json, fingerprint


def history(client):
    data = client.call('getReviewMaterialHistory', {'projectId': 148, 'gateType': 'FINAL_CUT', 'assetId': 2354})
    if not isinstance(data, list):
        raise ValueError('Expected Review version list')
    for row in data:
        if row['projectId'] != 148 or row['gateType'] != 'FINAL_CUT' or row['name'] != 'Carmilla | EP.02 | pt-BR':
            raise ValueError('Unexpected Review material scope')
    return data


def publish(config):
    root = Path('output/drama-01/episode-02/cartesia-v2-pilot')
    report = read_json(root/'render-report.json')
    video = root/'Carmilla_EP02_pt-BR_Cartesia_v2.mp4'
    if report['episode'] != 2 or report['model'] != 'sonic-3.6' or not report['video_payload_identical']:
        raise ValueError('Unverified pilot output')
    if digest(video) != report['output_sha256']:
        raise ValueError('Final video SHA changed')
    folder = Path('output/review-publication/148/Carmilla/cartesia-ep02-v2')
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
            if len(existing) != 1 or existing[0]['version'] != 2:
                raise ValueError('Uploaded URL unexpectedly registered')
            receipt = existing[0]
        else:
            if len(versions) != 1 or versions[0]['assetId'] != 2354 or versions[0]['version'] != 1:
                raise ValueError('Review already has another version; do not append v3')
            notes = ('Cartesia sonic-3.6 pilot, requested pt-BR; two saved cloned voices. '
                     '25 original dialogue cues retained, synthesized as 17 reviewed same-speaker groups. '
                     'Original video payload unchanged; original BGM/SFX retained. '
                     'Native accent support/listening and performance pending professional review; '
                     'no Portuguese emotion parameter applied. '
                     'Compare Quinze anos (v1 comment 7326), whisper, fear, NO and pacing. '
                     f'Timing flags: {report["timing_quality_review_count"]}; {report.get("subtitle_gap_review_count", 0)} short groups use following dialogue gaps, subtitle times unchanged. '
                     f'SHA256: {report["output_sha256"]}')
            material = {k: None for k in ('artDirectionSubMaterials', 'category', 'createdAt', 'documentKind',
                        'parentAssetId', 'status', 'updatedAt', 'version')}
            material.update({'assetId': 2354, 'projectId': 148, 'gateType': 'FINAL_CUT',
                             'name': versions[0]['name'], 'url': uploaded['url'],
                             'durationSeconds': round(report['duration_seconds']),
                             'tags': sorted(set(versions[0].get('tags') or []) | {'Carmilla', 'pt-BR', 'Cartesia'}),
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
        new = [v for v in versions if v.get('url') == uploaded['url'] and v.get('version') == 2]
        old = [v for v in versions if v.get('assetId') == 2354 and v.get('version') == 1]
        if len(new) != 1 or len(old) != 1 or new[0]['assetId'] == 2354:
            raise ValueError('Review version-chain readback failed')
        summary = {'status': 'uploaded_review_v2', 'project_id': 148,
                   'old_asset_id': 2354, 'asset_id': new[0]['assetId'], 'version': 2,
                   'url': uploaded['url'], 'sha256': report['output_sha256'],
                   'old_version_retained': True, 'native_ptBR_listening_reviewed': False}
        save_json(folder/'publication-result.json', summary)
        print('REVIEW_V2', summary['asset_id'], uploaded['url'], flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mcp-config', required=True, type=Path)
    args = p.parse_args()
    if sys.platform != 'win32':
        p.error('Business execution is Windows-only')
    publish(args.mcp_config)


if __name__ == '__main__':
    main()
