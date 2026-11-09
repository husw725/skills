"""Append a frozen Count candidate package and matching SRTs; never generate speech."""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import stat
import uuid
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from dub_episode import digest,safe_submit
from pipeline_publish import upload,protected,object_key,verify_object
from process_lock import process_lock
from publish_review import ReviewClient,materials
from translate import read_json,save_json,fingerprint

FILM='The Count of Monte Cristo';PROJECT=148


def scope_name(name,ep,gate):
    prefix=f'{FILM} | EP{ep:02d} | pt-BR | '
    return isinstance(name,str) and (name.startswith(prefix) or gate=='DOCUMENT' and re.fullmatch(re.escape(FILM)+rf' EP{ep:02d} V[1-9][0-9]*\.srt',name) is not None)


def history(client,asset,ep,gate):
    rows=client.call('getReviewMaterialHistory',dict(projectId=PROJECT,assetId=asset,gateType=gate))
    if not rows or any(r.get('projectId')!=PROJECT or r.get('gateType')!=gate or not scope_name(r.get('name'),ep,gate) or type(r.get('version')) is not int or r['version']<1 for r in rows):raise ValueError('Unexpected material history scope')
    return rows


def tuples(rows):return {(r['assetId'],r['version'],r['url']) for r in rows}


def append(client,row,url,folder,gate,subtitle=None):
    folder.mkdir(parents=True,exist_ok=True);kind='video' if gate=='FINAL_CUT' else 'subtitle';asset=row['old_'+kind+'_asset_id'];before=history(client,asset,row['episode'],gate);ip=folder/'version-intent.private.json'
    scope=dict(episode=row['episode'],kind=kind,old_asset=asset,old_url=row['old_'+kind+'_url'],old_version=row['old_'+kind+'_version'],new_url=url,sha256=row[kind+'_sha256'],subtitle=subtitle,delivery_note=row['delivery_note'])
    signature=fingerprint(scope)
    if not ip.exists():
        newest=max(before,key=lambda x:x['version'])
        if newest['assetId']!=asset or newest['url']!=scope['old_url'] or newest['version']!=scope['old_version'] or any(x['url']==url for x in before):raise ValueError('Current version differs; reconcile before append')
        version=newest['version']+1;spec={k:None for k in ('artDirectionSubMaterials','category','createdAt','parentAssetId','status','updatedAt','version')}
        spec.update(assetId=asset,projectId=PROJECT,gateType=gate,tags=[FILM],url=url)
        if gate=='DOCUMENT':spec.update(name=f'{FILM} EP{row["episode"]:02d} V{version}.srt',documentKind=newest.get('documentKind') or 'DOCUMENT',durationSeconds=0,note='pt-BR candidate subtitles matching the comment-revision video. '+row['delivery_note'])
        else:
            if not subtitle:raise ValueError('Matching delivered subtitle required')
            spec.update(name=f'{FILM} | EP{row["episode"]:02d} | pt-BR | V{version}',documentKind=None,durationSeconds=round(row['duration']),note=f'Comment-revision candidate. Matching subtitles: {subtitle["name"]}, document #{subtitle["assetId"]}. Native pronunciation, performance and mix listening remain pending. '+row['delivery_note'])
        save_json(ip,dict(scope=scope,fingerprint=signature,material=spec,material_fingerprint=fingerprint(spec),before=[list(x) for x in sorted(tuples(before))],expected_version=version))
    intent=read_json(ip);spec=intent['material'];old=set(map(tuple,intent['before']))
    if intent.get('material_fingerprint')!=fingerprint(spec) or intent['fingerprint']!=signature or intent['scope']!=scope or spec['projectId']!=PROJECT or spec['gateType']!=gate or spec['assetId']!=asset or spec['url']!=url or spec['tags']!=[FILM] or not scope_name(spec['name'],row['episode'],gate) or intent['expected_version']!=scope['old_version']+1 or not old.issubset(tuples(before)):raise ValueError('Append intent/history differs')
    found=[x for x in before if x['url']==url]
    if not found:
        if tuples(before)!=old:raise ValueError('Concurrent version change; no append issued')
        safe_submit(client,'updateReviewMaterialVersion',{'material':spec},folder/'version-submission.private.json')
    after=history(client,asset,row['episode'],gate);found=[x for x in after if x['url']==url]
    if len(found)!=1 or found[0]['version']!=intent['expected_version'] or found[0].get('tags')!=[FILM] or found[0].get('name')!=spec['name'] or not old.issubset(tuples(after)):raise ValueError('Append/history preservation not confirmed')
    save_json(folder/'history-after.private.json',after);return found[0]


def validate_manifest(m):
    rows=m.get('episodes',[])
    if m.get('target_project')!=PROJECT or m.get('film')!=FILM or len(rows)!=32 or any(type(x.get('episode')) is not int for x in rows) or {x['episode'] for x in rows}!=set(range(1,33)):raise ValueError('Exact 32 episode package required')
    if len({r.get('old_video_asset_id') for r in rows})!=32 or len({r.get('old_subtitle_asset_id') for r in rows})!=32:raise ValueError('Distinct per-episode source assets required')
    for r in rows:
        if type(r.get('duration')) not in (int,float) or not math.isfinite(r['duration']) or r['duration']<=0:raise ValueError('Finite positive duration required')
        for kind in ('video','subtitle'):
            u=urlsplit(r.get('old_'+kind+'_url',''))
            if u.scheme!='https' or u.hostname!='starlitshorts.s3.amazonaws.com' or u.username or u.password or not u.path.startswith('/aigc/uploads/mcp/review/'):raise ValueError('Unexpected original object URL scope')
        if type(r.get('reuse_video')) is not bool or type(r.get('subtitle_changed')) is not bool:raise ValueError('Explicit reuse/subtitle flags required')
        for kind in ('video','subtitle'):
            if type(r.get('old_'+kind+'_asset_id')) is not int or type(r.get('old_'+kind+'_version')) is not int or r['old_'+kind+'_asset_id']<=0 or r['old_'+kind+'_version']<1:raise ValueError('Typed original material identity required')
            if not re.fullmatch('[a-f0-9]{64}',r.get(kind+'_sha256','')) or not re.fullmatch('[a-f0-9]{64}',r.get('old_'+kind+'_sha256','')):raise ValueError('Exact source/output hashes required')
        if r['subtitle_changed']!=(r['subtitle_sha256']!=r['old_subtitle_sha256']):raise ValueError('Subtitle changed flag disagrees with bytes')
        if r['reuse_video'] and (r['video_sha256']!=r['old_video_sha256'] or r['subtitle_changed']):raise ValueError('Reuse must retain original picture/audio/subtitle package')
        if r['subtitle_changed'] and Path(r['subtitle_path']).name!=f'{FILM} EP{r["episode"]:02d} V{r["old_subtitle_version"]+1}.srt':raise ValueError('Clear next-version SRT filename required')
    return rows



def freeze(source,target,expected_sha):
    """Copy approved bytes once; transfers only consume this private read-only copy."""
    source=Path(source);target=Path(target)
    if target.exists():
        if digest(target)!=expected_sha:raise ValueError('Frozen transfer copy changed')
        return target
    target.parent.mkdir(parents=True,exist_ok=True);part=target.with_name(target.name+'.copying-'+uuid.uuid4().hex);h=hashlib.sha256()
    with source.open('rb') as src,part.open('xb') as dst:
        for block in iter(lambda:src.read(1024*1024),b''):h.update(block);dst.write(block)
        dst.flush();os.fsync(dst.fileno())
    if h.hexdigest()!=expected_sha:raise ValueError('Source changed during frozen copy; no upload allowed')
    part.replace(target);target.chmod(stat.S_IREAD)
    if digest(target)!=expected_sha:raise ValueError('Frozen copy verification failed')
    return target


def check_frozen(row):
    for kind in ('video','subtitle'):
        if digest(row[kind+'_path'])!=row[kind+'_sha256']:raise ValueError('Approved frozen transfer input changed')


def preserve(before,after):
    observed=protected([r for r in after if str(r['assetId']) in before])
    if observed!=before:raise ValueError('Protected existing assets changed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('manifest','approval','output','config'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--aws-config',type=Path);a=p.parse_args()
    if sys.platform!='win32':raise ValueError('Business publishing runs on Windows')
    data=a.manifest.read_bytes();sig=hashlib.sha256(data).hexdigest();m=json.loads(data.decode('utf-8-sig'));rows=validate_manifest(m);approval=read_json(a.approval)
    if approval.get('manifest_sha256')!=sig or approval.get('technical_candidate_delivery_approved') is not True or digest(approval['audit_report_path'])!=approval['audit_report_sha256']:raise ValueError('Independent candidate package delivery review required')
    if a.output.resolve()!=(Path('output/review-publication/148/Count-comment-revisions')/sig).resolve():raise ValueError('Use canonical manifest-keyed publication ledger')
    a.output.mkdir(parents=True,exist_ok=True)
    with process_lock(Path('output/review-publication/target-review-148-publication.lock'),timeout=0),process_lock(a.output/'publish.lock',timeout=0):
        client=ReviewClient(a.config,a.output/'service-error.private.json');initial=materials(client,PROJECT);source=protected(materials(client,100));byid={r['assetId']:r for r in initial}
        altered={r['old_video_asset_id'] for r in rows if not r['reuse_video']}|{r['old_subtitle_asset_id'] for r in rows if r['subtitle_changed']};immutable=protected([r for r in initial if r['assetId'] not in altered]);keys={object_key(r['url']) for r in initial+materials(client,100) if r.get('url')};prepared=[]
        # Validate the entire local package and all original histories before the first PUT/append.
        for row in rows:
            if digest(row['video_path'])!=row['video_sha256'] or digest(row['subtitle_path'])!=row['subtitle_sha256'] or digest(row['report_path'])!=row['report_sha256']:raise ValueError('Frozen delivery file changed')
            report_bytes=Path(row['report_path']).read_bytes()
            if hashlib.sha256(report_bytes).hexdigest()!=row['report_sha256']:raise ValueError('Bound report snapshot changed')
            report=json.loads(report_bytes.decode('utf-8-sig'))
            if report.get('output_sha256')!=row['video_sha256'] or report.get('subtitle_sha256')!=row['subtitle_sha256'] or report.get('picture_payload_identical') is not True or report.get('full_decode_passed') is not True:raise ValueError('Media validation evidence differs')
            for kind,gate in [('video','FINAL_CUT'),('subtitle','DOCUMENT')]:
                h=history(client,row['old_'+kind+'_asset_id'],row['episode'],gate)
                for old in h:
                    if old.get('url'):keys.add(object_key(old['url']))
                expected=(row['old_'+kind+'_asset_id'],row['old_'+kind+'_version'],row['old_'+kind+'_url'])
                if expected not in tuples(h):raise ValueError('Frozen original material not in history')
                latest=max(h,key=lambda x:x['version']);intent=a.output/f'episode-{row["episode"]:02d}'/kind/'version-intent.private.json'
                if not intent.exists() and (latest['assetId'],latest['version'],latest['url'])!=expected:raise ValueError('Current original version changed before publication')
            folder=a.output/f'episode-{row["episode"]:02d}';folder.mkdir(exist_ok=True);lp=folder/'upload-ledger.private.json';ledger=read_json(lp) if lp.exists() else {'uploads':{}}
            copied=dict(row);copied['video_path']=str(freeze(row['video_path'],folder/'frozen/video.mp4',row['video_sha256']));copied['subtitle_path']=str(freeze(row['subtitle_path'],folder/'frozen'/Path(row['subtitle_path']).name,row['subtitle_sha256']));check_frozen(copied)
            prepared.append((copied,folder,lp,ledger))
        urls={};s3=None
        if a.aws_config:
            from scoped_s3_transfer import client as aws_client,reserve,upload_reserved,verify_public
            s3=aws_client(read_json(a.aws_config));entries=[]
            for row,folder,lp,ledger in prepared:
                if row['reuse_video']:urls[row['episode']]=row['old_video_url'];continue
                check_frozen(row);video=Path(row['video_path']);item,key=reserve(client,video,ledger,lp,keys);keys.add(object_key(item['url']));entries.append((row,video,lp,ledger,item,key))
            def transfer(e):
                row,video,lp,ledger,item,key=e
                check_frozen(row);url=upload_reserved(s3,video,ledger,lp,item,key);check_frozen(row)
                return row['episode'],url
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(transfer,e) for e in entries]
                for future in concurrent.futures.as_completed(futures):
                    ep,url=future.result();urls[ep]=url;print('COMMENT_VIDEO_OBJECT_VERIFIED',ep,flush=True)
        else:
            from scoped_s3_transfer import reserve
            for row,folder,lp,ledger in prepared:
                if row['reuse_video']:urls[row['episode']]=row['old_video_url'];continue
                check_frozen(row);video=Path(row['video_path']);reserve(client,video,ledger,lp,keys)
                urls[row['episode']]=upload(client,video,ledger,lp,keys);keys.add(object_key(urls[row['episode']]))
        delivered=[]
        for row,folder,lp,ledger in prepared:
            check_frozen(row);ep=row['episode'];video=Path(row['video_path']);sub=Path(row['subtitle_path'])
            if row['reuse_video']:verify_object(client,urls[ep],video)
            elif s3:verify_public(client.http,video,urls[ep])
            if row['subtitle_changed']:
                from scoped_s3_transfer import reserve
                reserve(client,sub,ledger,lp,keys);suburl=upload(client,sub,ledger,lp,keys,content_headers={'Content-Type':'application/x-subrip; charset=utf-8','Content-Disposition':f'attachment; filename="{sub.name}"'})
            else:suburl=row['old_subtitle_url']
            keys.add(object_key(suburl))
            check_frozen(row)
            if row['subtitle_changed']:subrow=append(client,row,suburl,folder/'subtitle','DOCUMENT')
            else:
                subrow=max(history(client,row['old_subtitle_asset_id'],ep,'DOCUMENT'),key=lambda x:x['version'])
                if subrow['assetId']!=row['old_subtitle_asset_id'] or subrow['url']!=suburl:raise ValueError('Unchanged subtitle identity differs')
                verify_object(client,suburl,sub)
            check_frozen(row)
            if row['reuse_video']:vrow=max(history(client,row['old_video_asset_id'],ep,'FINAL_CUT'),key=lambda x:x['version'])
            else:vrow=append(client,row,urls[ep],folder/'video','FINAL_CUT',dict(assetId=subrow['assetId'],name=subrow['name']))
            result=dict(episode=ep,video_asset_id=vrow['assetId'],video_version=vrow['version'],video_url=vrow['url'],video_sha256=row['video_sha256'],subtitle_asset_id=subrow['assetId'],subtitle_version=subrow['version'],subtitle_url=subrow['url'],subtitle_sha256=row['subtitle_sha256'],reused_video=row['reuse_video'],native_listening_passed=False,published_at=time.time());save_json(folder/'delivered.private.json',result);delivered.append(result);print('COMMENT_PACKAGE_EPISODE_VERIFIED',ep,flush=True)
        after=materials(client,PROJECT);current={r['assetId']:r for r in after}
        for r in delivered:
            for kind,gate in [('video','FINAL_CUT'),('subtitle','DOCUMENT')]:
                material=current.get(r[kind+'_asset_id'])
                if material is None or material['gateType']!=gate or material['projectId']!=PROJECT or material['version']!=r[kind+'_version'] or material['url']!=r[kind+'_url']:raise ValueError('Final current package readback differs')
        preserve(immutable,after);preserve(source,materials(client,100));save_json(a.output/'complete.private.json',dict(manifest_sha256=sig,episodes=delivered,source_and_other_assets_preserved=True,native_listening_passed=False,completed_at=time.time()))


if __name__=='__main__':main()
