"""Append explicitly approved background candidates to existing Review histories."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import time

from dub_episode import digest, probe, safe_submit
from pipeline_publish import upload, protected, object_key
from process_lock import process_lock
from publish_review import ReviewClient, materials
from translate import read_json, save_json, fingerprint

FILM = 'The Count of Monte Cristo'
PROJECT = 148


def history(client, asset, episode):
    rows = client.call('getReviewMaterialHistory', {'projectId': PROJECT, 'assetId': asset, 'gateType': 'FINAL_CUT'})
    prefix = f'{FILM} | EP{episode:02d} | pt-BR | '
    if not rows or any(r.get('projectId') != PROJECT or r.get('gateType') != 'FINAL_CUT' or not r.get('name', '').startswith(prefix) for r in rows):
        raise ValueError('Unexpected history scope')
    return rows


def append_version(client, row, url, folder):
    folder = Path(folder);folder.mkdir(parents=True, exist_ok=True)
    rows = history(client, row['old_video_asset_id'], row['episode'])
    intent = folder/'version-intent.private.json'
    if not intent.exists():
        if any(r.get('url') == url for r in rows):raise ValueError('Existing version without local intent; reconcile')
        newest = max(rows, key=lambda r: r['version'])
        if newest['assetId'] != row['old_video_asset_id'] or newest['url'] != row['old_video_url']:
            raise ValueError('Current version differs from frozen delivery scope')
        spec = {k: None for k in ('artDirectionSubMaterials','category','createdAt','documentKind','parentAssetId','status','updatedAt','version')}
        spec.update(assetId=newest['assetId'], projectId=PROJECT, gateType='FINAL_CUT',
                    name=f'{FILM} | EP{row["episode"]:02d} | pt-BR | {row["video_sha256"][:12]}',
                    url=url, durationSeconds=round(row['duration']), tags=[FILM],
                    note='Background revision candidate; existing paid Portuguese dialogue and picture retained. '
                         f'Unchanged subtitle asset #{row["subtitle_asset_id"]}, SHA256 {row["subtitle_sha256"]}. '
                         'Machine screening and technical checks are not native approval. '
                         f'Video SHA256 {row["video_sha256"]}. '+row['delivery_note'])
        save_json(intent, {'material': spec, 'episode': row['episode'], 'video_sha256': row['video_sha256'],
                          'expected_version': newest['version']+1,
                          'input_fingerprint': fingerprint({'row': row, 'url': url}),
                          'before': [[r['assetId'], r['version'], r['url']] for r in rows]})
    data = read_json(intent);spec = data['material'];before = data['before']
    if (data.get('input_fingerprint') != fingerprint({'row': row, 'url': url})
            or data['episode'] != row['episode'] or data['video_sha256'] != row['video_sha256'] or spec['url'] != url
            or spec['projectId'] != PROJECT or spec['gateType'] != 'FINAL_CUT' or spec['tags'] != [FILM]
            or spec['assetId'] != row['old_video_asset_id'] or data['expected_version'] != max(x[1] for x in before)+1
            or not set(map(tuple,before)).issubset({(r['assetId'],r['version'],r['url']) for r in rows})):
        raise ValueError('Publication intent/history changed')
    found = [r for r in rows if r.get('url') == url]
    if not found:
        if {(r['assetId'],r['version'],r['url']) for r in rows} != set(map(tuple,before)):
            raise ValueError('Concurrent history change; reconcile')
        safe_submit(client, 'updateReviewMaterialVersion', {'material': spec}, folder/'version-submission.private.json')
    rows = history(client, row['old_video_asset_id'], row['episode'])
    found = [r for r in rows if r.get('url') == url]
    if (len(found) != 1 or found[0]['version'] != data['expected_version'] or found[0].get('tags') != [FILM]
            or not set(map(tuple,before)).issubset({(r['assetId'],r['version'],r['url']) for r in rows})):
        raise ValueError('Version append/history preservation not confirmed')
    save_json(folder/'history-after.private.json', rows)
    return found[0]


def verify_subtitle(client, row, material_rows):
    found = [r for r in material_rows if r.get('assetId') == row['subtitle_asset_id']]
    prefix = f'{FILM} | EP{row["episode"]:02d} | pt-BR | '
    if (len(found) != 1 or found[0].get('projectId') != PROJECT
            or found[0].get('gateType') != 'DOCUMENT' or not found[0].get('name', '').startswith(prefix)
            or found[0].get('url') != row['subtitle_url']):
        raise ValueError('Remote subtitle identity differs')
    h = hashlib.sha256();size = 0
    with client.http.get(row['subtitle_url'], stream=True, timeout=60, allow_redirects=False,
                         headers={'Accept-Encoding':'identity'}) as response:
        if response.status_code != 200:raise ValueError('Remote subtitle unavailable')
        for block in response.iter_content(1024*64):
            size += len(block)
            if size > row['subtitle_bytes']:raise ValueError('Remote subtitle too large')
            h.update(block)
    if size != row['subtitle_bytes'] or h.hexdigest() != row['subtitle_sha256']:
        raise ValueError('Remote subtitle content differs')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True);p.add_argument('--approval', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True);p.add_argument('--config', type=Path, required=True)
    p.add_argument('--ffmpeg', type=Path, required=True)
    p.add_argument('--aws-config', type=Path, help='Optional private credentials for reserved-object multipart transfer')
    a = p.parse_args()
    if sys.platform != 'win32':raise ValueError('Business publishing runs on Windows')
    data = a.manifest.read_bytes();signature = hashlib.sha256(data).hexdigest()
    manifest = json.loads(data.decode('utf-8-sig'));approval = read_json(a.approval)
    if (approval.get('manifest_sha256') != signature or approval.get('technical_candidate_delivery_approved') is not True
            or manifest.get('target_project') != PROJECT or manifest.get('film') != FILM
            or {r['episode'] for r in manifest['episodes']} != set(range(1,33)) or len(manifest['episodes']) != 32):
        raise ValueError('Whole-season candidate delivery approval required')
    canonical = Path('output/review-publication/148/Count-background-revisions')/signature
    if a.output.resolve() != canonical.resolve():
        raise ValueError('Use canonical publication ledger directory keyed by manifest SHA')
    a.output.mkdir(parents=True,exist_ok=True)
    with process_lock(Path('output/review-publication/target-review-148-publication.lock'), timeout=0), process_lock(a.output/'publish.lock', timeout=0):
        binding = a.output/'scope.private.json'
        if binding.exists() and read_json(binding) != {'manifest_sha256':signature}:raise ValueError('Scope changed')
        save_json(binding,{'manifest_sha256':signature})
        client = ReviewClient(a.config,a.output/'service-error.private.json')
        initial = materials(client,PROJECT);source = protected(materials(client,100))
        immutable = protected([r for r in initial if not (r.get('gateType')=='FINAL_CUT' and FILM in (r.get('tags')or[]))])
        protected_keys = {object_key(r['url']) for r in initial+materials(client,100) if r.get('url')}
        for row in manifest['episodes']:
            verify_subtitle(client,row,initial)
            for old in history(client,row['old_video_asset_id'],row['episode']):
                if old.get('url'):protected_keys.add(object_key(old['url']))
        prepared=[]
        for row in manifest['episodes']:
            report = read_json(row['report_path']);video=Path(report['output']);subtitle=Path(report['subtitle'])
            if (digest(row['report_path']) != row['report_sha256'] or digest(video) != row['video_sha256']
                    or digest(subtitle) != row['subtitle_sha256'] or report['output_sha256'] != row['video_sha256']
                    or report['subtitle_sha256'] != row['subtitle_sha256'] or not report.get('picture_payload_identical')
                    or not report.get('full_decode_passed') or report.get('new_tts') != 0 or report.get('new_clones') != 0):
                raise ValueError('Approved candidate changed')
            folder = a.output/f'episode-{row["episode"]:02d}';folder.mkdir(exist_ok=True)
            ledger_path=folder/'upload-ledger.private.json';ledger=read_json(ledger_path) if ledger_path.exists() else {'uploads':{}}
            prepared.append((row,video,folder,ledger_path,ledger))
        urls={}
        if a.aws_config:
            from scoped_s3_transfer import client as aws_client,reserve,upload_reserved
            s3=aws_client(read_json(a.aws_config));reserved=[]
            # All URLs are allocated and protected serially before concurrent data PUTs.
            for row,video,folder,ledger_path,ledger in prepared:
                item,key=reserve(client,video,ledger,ledger_path,protected_keys)
                protected_keys.add(object_key(item['url']))
                reserved.append((row,video,ledger_path,ledger,item,key))
            failures=[]
            def transfer(entry):
                row,video,ledger_path,ledger,item,key=entry
                return row['episode'],upload_reserved(s3,video,ledger,ledger_path,item,key)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                futures={pool.submit(transfer,entry):entry[0]['episode'] for entry in reserved}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        ep,url=future.result();urls[ep]=url
                        print('BACKGROUND_OBJECT_VERIFIED',ep,flush=True)
                    except Exception as error:
                        failures.append({'episode':futures[future],'error_type':type(error).__name__})
                    save_json(a.output/'upload-progress.private.json',{'verified':len(urls),'total':32,'failures':failures})
            if failures:raise ValueError('Some multipart outcomes need reconciliation; no new versions appended')
        else:
            for row,video,folder,ledger_path,ledger in prepared:
                urls[row['episode']]=upload(client,video,ledger,ledger_path,protected_keys)
                protected_keys.add(object_key(urls[row['episode']]))
        # Check anonymously, separate from authenticated checksum proof.
        if a.aws_config:
            from scoped_s3_transfer import verify_public
            for row,video,folder,ledger_path,ledger in prepared:
                verify_public(client.http,video,urls[row['episode']])
                ledger['uploads'][row['video_sha256']]['public_read_verified']=True
                save_json(ledger_path,ledger)
        for row,video,folder,ledger_path,ledger in prepared:
            url=urls[row['episode']]
            result=append_version(client,row,url,folder)
            save_json(folder/'delivered.private.json',{'episode':row['episode'],'video_asset_id':result['assetId'],
                'version':result['version'],'url':url,'video_sha256':row['video_sha256'],
                'subtitle_asset_id':row['subtitle_asset_id'],'subtitle_sha256':row['subtitle_sha256'],
                'native_listening_passed':False,'published_at':time.time()})
            print('BACKGROUND_VERSION_DELIVERED',row['episode'],result['assetId'],flush=True)
        after=materials(client,PROJECT)
        actual=protected([r for r in after if str(r['assetId']) in immutable])
        if actual != immutable or protected(materials(client,100)) != source:raise ValueError('Protected assets changed')
        save_json(a.output/'complete.private.json',{'manifest_sha256':signature,'delivered':32,
            'source_and_other_assets_preserved':True,'native_listening_passed':False,'completed_at':time.time()})


if __name__=='__main__':main()
