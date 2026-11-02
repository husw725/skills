"""Replace technical tags with film names using metadata-only updates and fresh readback."""
import argparse
from pathlib import Path
import sys

from dub_episode import digest
from pipeline_publish import FILMS
from process_lock import process_lock
from publish_review import ReviewClient, materials
from translate import read_json, save_json


GUARD = ('assetId', 'projectId', 'gateType', 'name', 'url', 'version',
         'parentAssetId', 'documentKind', 'category', 'durationSeconds', 'note')


def patch(row):
    if row['projectId'] != 148 or row['gateType'] != 'FINAL_CUT':
        raise ValueError('Only target-project final cuts are in the cleanup scope')
    names = [film for film in (*FILMS.values(), 'Carmilla') if row['name'].startswith(film+' |')]
    if len(names) != 1:
        raise ValueError('Film must be unambiguous from the material name')
    return dict(projectId=148, gateType='FINAL_CUT', assetId=row['assetId'], tags=names)


def unchanged(before, after):
    return all(before.get(k) == after.get(k) for k in GUARD)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    args = p.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Windows business metadata execution only')
    plan = read_json(args.plan); original = read_json(args.snapshot)
    if plan['project_id'] != 148 or digest(args.snapshot) != plan['source_snapshot_sha256'] or plan['unresolved']:
        raise ValueError('Exact reviewed cleanup snapshot required')
    before = {r['assetId']: r for r in original}
    changes = plan['changes']
    if (not 1 <= len(changes) <= 500 or len({c['asset_id'] for c in changes}) != len(changes)
            or any(patch(before[c['asset_id']])['tags'] != c['tags'] for c in changes)):
        raise ValueError('Film-only scope differs from the saved materials')
    root = args.plan.parent; receipt = root/'tag-cleanup-receipts.private.json'
    with process_lock(root/'tag-cleanup.lock', timeout=0):
        ledger = read_json(receipt) if receipt.exists() else dict(plan_sha256=digest(args.plan), items={})
        if ledger['plan_sha256'] != digest(args.plan):
            raise ValueError('Cleanup plan changed; preserve existing update receipts')
        client = ReviewClient(args.config, root/'tag-update-service-error.private.json')
        current = {r['assetId']: r for r in materials(client, 148)}
        for change in changes:
            key = change['asset_id']; old = before[key]; request = patch(old)
            if not unchanged(old, current[key]):
                raise ValueError('Material identity or content changed before cleanup')
            if current[key].get('tags') != request['tags']:
                if current[key].get('tags') != old.get('tags'):
                    raise ValueError('Concurrent tag edits need reconciliation')
                ledger['items'][str(key)] = dict(status='updating', before_tags=old.get('tags'), tags=request['tags'])
                save_json(receipt, ledger)
                # The documented endpoint accepts only supplied metadata fields.
                # Never send URL, status, version, or unrelated null fields.
                result = client.call('updateReviewMaterial', dict(material=request))
                if not isinstance(result, dict) or result.get('assetId') != key:
                    result = next(r for r in materials(client, 148) if r['assetId'] == key)
                if not unchanged(old, result) or result.get('tags') != request['tags']:
                    raise ValueError('Metadata update readback differs; inspect without another update')
                current[key] = result
            ledger['items'][str(key)] = dict(status='verified', before_tags=old.get('tags'), tags=request['tags'])
            save_json(receipt, ledger)
            print('FILM_TAG_VERIFIED', key, request['tags'][0], flush=True)
        after = {r['assetId']: r for r in materials(client, 148)}
        targets = {c['asset_id'] for c in changes}
        for key, old in before.items():
            if key not in after or not unchanged(old, after[key]):
                raise ValueError('Protected material identity/content changed')
            wanted = patch(old)['tags'] if key in targets else old.get('tags')
            if after[key].get('tags') != wanted:
                raise ValueError('Final tag inventory differs')
        save_json(root/'materials-after.private.json', list(after.values()))
        save_json(root/'tag-cleanup-result.private.json', dict(updated=len(changes), project_id=148,
                  film_tags=sorted({tag for key in targets for tag in after[key]['tags']}),
                  files_and_versions_unchanged=True))
        print('FILM_TAG_CLEANUP_COMPLETE', len(changes))


if __name__ == '__main__':
    main()
