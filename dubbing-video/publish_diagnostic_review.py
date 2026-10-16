"""Append only the two requested diagnostic candidates to their Review histories."""
import argparse
from pathlib import Path
import sys
from dub_episode import digest, safe_submit
from mflix_client import Mflix
from process_lock import process_lock
from translate import read_json, save_json, fingerprint


def history(client, n):
    old = {7: 2359, 29: 2381}[n]
    rows = client.call('getReviewMaterialHistory', {'projectId': 148, 'gateType': 'FINAL_CUT', 'assetId': old})
    if not isinstance(rows, list) or not rows:
        raise ValueError('Expected existing version history')
    for r in rows:
        if (r['projectId'], r['gateType'], r['name']) != (148, 'FINAL_CUT', f'Carmilla | EP.{n:02} | pt-BR'):
            raise ValueError('Unexpected Review scope')
    return rows


def publish(n, config):
    if n not in (7, 29): raise ValueError('Outside diagnostic scope')
    root = Path(f'output/drama-01/episode-{n:02}/diagnostic-v2')
    report = read_json(root/'render-report.json')
    video = root/f'Carmilla_EP{n:02}_pt-BR_diagnostic_v2.mp4'
    if (report['episode'] != n or report['status'] != 'rendered_diagnostic_candidate'
            or not report['video_payload_identical'] or report['new_clone_count'] != 0
            or report['new_tts_task_count'] != {7: 13, 29: 14}[n]
            or digest(video) != report['output_sha256']):
        raise ValueError('Unverified diagnostic candidate')
    folder = Path(f'output/review-publication/148/Carmilla/diagnostic-ep{n:02}-v2')
    folder.mkdir(parents=True, exist_ok=True)
    with process_lock(folder/'publish.lock', timeout=0):
        uploaded = read_json(folder/'upload.private.json')
        if uploaded['sha256'] != report['output_sha256'] or not uploaded.get('remote_sha256_verified'):
            raise ValueError('Verified S3 receipt required')
        client = Mflix(config); rows = history(client, n)
        save_json(folder/'history-before.private.json', rows)
        old = {7: 2359, 29: 2381}[n]
        existing = [r for r in rows if r.get('url') == uploaded['url']]
        if existing:
            if len(existing) != 1 or existing[0]['version'] != 2:
                raise ValueError('Unexpected existing URL registration')
        else:
            if {(r['assetId'], r['version']) for r in rows} != {(old, 1)}:
                raise ValueError('Another version exists; do not append v3')
            extra = ('EP07: review panicked CAMILA at 9s, the long question near 46s, '
                     'corajosa/ou tola near 64-68s and cold voiceover near 71s.' if n == 7 else
                     'EP29: review Father alarm near 37-40s, tomorrow/ritual near 65-68s, '
                     'Irina threat near 76-81s. Cue 8 near 47s has inconsistent source/script wording '
                     'and unknown evidence speaker: old fitted audio reused, NOT claimed repaired.')
            material = {k: None for k in ('artDirectionSubMaterials', 'category', 'createdAt', 'documentKind',
                        'parentAssetId', 'status', 'updatedAt', 'version')}
            material.update({'assetId': old, 'projectId': 148, 'gateType': 'FINAL_CUT',
                'name': rows[0]['name'], 'url': uploaded['url'],
                'durationSeconds': round(report['duration_seconds']),
                'tags': sorted(set(rows[0].get('tags') or []) | {'Carmilla', 'pt-BR', 'Cartesia', 'MiniMax'}),
                'note': ('Diagnostic review candidate, not native-approved. Existing Cartesia voices for main '
                         'dialogue; existing MiniMax voices for selected emotional roles/lines; ZERO new clones. '
                         'Original subtitle wording/timecodes and video payload preserved; same-role phrase grouping. '
                         'Check Brazilian accent, pronunciation, emotion, timbre switches, timing and mix separately. '
                         'Cartesia pt-BR emotion/accent metadata not verified. No automatic acceptance from API success. '
                         +extra+' SHA256: '+report['output_sha256'])})
            signature = fingerprint(material); sig = folder/'request-fingerprint.json'
            if sig.exists() and read_json(sig)['fingerprint'] != signature:
                raise ValueError('Publication request changed')
            save_json(sig, {'fingerprint': signature})
            safe_submit(client, 'updateReviewMaterialVersion', {'material': material},
                        folder/'version-submission.private.json')
        rows = history(client, n); save_json(folder/'history-after.private.json', rows)
        new = [r for r in rows if r.get('url') == uploaded['url'] and r['version'] == 2]
        if len(new) != 1 or new[0]['assetId'] == old or not any(r['assetId'] == old and r['version'] == 1 for r in rows):
            raise ValueError('Version-chain readback failed')
        summary = {'episode': n, 'project_id': 148, 'asset_id': new[0]['assetId'], 'version': 2,
                   'url': uploaded['url'], 'sha256': report['output_sha256'], 'old_version_retained': True,
                   'native_ptBR_listening_reviewed': False}
        save_json(folder/'publication-result.json', summary)
        print('REVIEW_DIAGNOSTIC', n, summary['asset_id'], uploaded['url'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--episode', type=int, choices=(7, 29), required=True)
    p.add_argument('--mcp-config', type=Path, required=True); a = p.parse_args()
    if sys.platform != 'win32': p.error('Business execution is Windows-only')
    publish(a.episode, a.mcp_config)
