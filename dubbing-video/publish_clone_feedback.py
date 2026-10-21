"""Add one clearly marked clone A/B audition to Review, preserving episode assets."""
import argparse
import hashlib
from pathlib import Path
import re
import sys
import time
import unicodedata
import requests
from translate import read_json,save_json,fingerprint
from dub_episode import digest
from process_lock import process_lock
from mflix_client import Mflix
from publish_review import materials,register,check_matches
from notify_season_complete import verify_delivery
from clone_feedback_pilot import ROOT,validate


def main():
 p=argparse.ArgumentParser();p.add_argument('--mcp-config',required=True,type=Path);a=p.parse_args()
 if sys.platform!='win32':p.error('Publish on Windows')
 with process_lock(ROOT/'publication.lock',timeout=0):
  manifest=read_json(ROOT/'manifest.private.json');validate(manifest)
  report=read_json(ROOT/'reel-report.private.json');generation=read_json(ROOT/'generation-result.private.json')['results']
  path=ROOT/'Carmilla_existing_clone_feedback_AB_v1.mp4';sha=digest(path)
  if (report['manifest_sha256']!=digest(ROOT/'manifest.private.json') or report['generation_sha256']!=digest(ROOT/'generation-result.private.json')
   or report['output_sha256']!=sha or report['case_count']!=9 or len(report['clips'])!=18
   or report['new_clone_count']!=0 or report['episode_replaced']):raise ValueError('Unverified clone audition')
  for r in generation.values():
   if digest(r['path'])!=r['sha256']:raise ValueError('Generated audition changed')
  screened=read_json(ROOT/'content-screening.private.json')['results']
  if len(screened)!=9:raise ValueError('Content screening incomplete')
  for case,r in zip(manifest['cases'],screened):
   g=generation[fingerprint(case['request'])]
   if r['case_id']!=case['id'] or r['audio_sha256']!=g['sha256'] or r['expected_text']!=case['caption']:raise ValueError('Content screening differs from audition')
  client=Mflix(a.mcp_config);rows=materials(client,148)
  base=read_json('output/subtitle-review-update-20261020/live-before.private.json')
  verify_delivery({'all_32_published':True,'published':base['published']},rows)
  upload_path=ROOT/'review-upload.private.json'
  if upload_path.exists():
   upload=read_json(upload_path)
   if upload['sha256']!=sha:raise ValueError('Prior uploaded reel differs')
  else:
   signed=client.call('createFilePresignedUrl',{'originalFileName':path.name})
   if not isinstance(signed,str) or not signed.startswith('https://'):raise ValueError('Expected HTTPS upload URL')
   upload={'sha256':sha,'signed_url':signed,'url':signed.split('?')[0],'status':'uploading'};save_json(upload_path,upload)
  if upload['status']!='uploaded':
   body=path.read_bytes()
   if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('Upload bytes changed')
   try:
    response=client.http.put(upload['signed_url'],data=body,timeout=120);response.raise_for_status()
   except requests.RequestException:raise RuntimeError('Audition upload failed; object checkpoint retained') from None
   upload['status']='uploaded';save_json(upload_path,upload)
  norm=lambda s:re.sub(r'[^\w]+','',unicodedata.normalize('NFC',s).casefold())
  differences=[r for r in screened if norm(r['expected_text'])!=norm(r['asr_transcript'])]
  note=('现有角色克隆音色定点A/B试听：9个明确变量候选，18张卡。A为当前已对齐干声；B为新请求原始干声。'
   'Laura/Father/Irina均沿用对应原片同一voice ID，新增克隆0。未改译稿、字幕、剧集视频或正式分组；B未对时。'
   'Irina整段auto仅连续音色诊断，不代表跨情绪表演已通过。巴葡发音、表演与音色相似度待专业听审。'
   'ASR分歧仅听审定位，不是已确认发错。')
  for r in differences:note+=f'\n{r["case_id"]}: 目标「{r["expected_text"]}」/ ASR「{r["asr_transcript"]}」'
  note+=f'\nSHA256: {sha}'
  spec={'projectId':148,'gateType':'FINAL_CUT','name':f'Carmilla | Existing clone pt-BR | Feedback A-B v1 | {sha[:12]}',
   'url':upload['url'],'tags':['Carmilla','pt-BR','existing-clone','audition'],'durationSeconds':round(report['duration_seconds']),'note':note}
  ledger_path=ROOT/'review-ledger.private.json';ledger=read_json(ledger_path) if ledger_path.exists() else {'items':{}}
  asset=register(client,spec,ledger,ledger_path);row=check_matches(materials(client,148),spec)
  if row['assetId']!=asset or row['note']!=note:raise ValueError('Review audition readback differs')
  try:
   response=requests.get(upload['url'],timeout=90);response.raise_for_status()
  except requests.RequestException:raise RuntimeError('Audition public verification failed; registration retained') from None
  if hashlib.sha256(response.content).hexdigest()!=sha:raise ValueError('Public audition bytes differ')
  save_json(ROOT/'publication-result.private.json',{'asset_id':asset,'project_id':148,'name':spec['name'],'url':upload['url'],
   'sha256':sha,'verified_at':time.time(),'new_clone_count':0,'native_listening_passed':False})
  print('CLONE_AB_REVIEW_VERIFIED',asset,flush=True)


if __name__=='__main__':main()
