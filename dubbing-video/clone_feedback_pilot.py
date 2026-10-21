"""Bounded existing-clone A/B auditions; no clone creation or episode replacement."""
import argparse
import copy
import re
from pathlib import Path
import subprocess
import sys
import time

from translate import read_json,save_json,fingerprint
from dub_episode import digest,read_audio,write_audio,RATE,probe
from process_lock import process_lock
from cartesia_pilot import bind
from repair_episode_feedback import generate
from rerun_carmilla_season import paid_audio_folder,paid_cache_roots
from publish_season_candidates import candidates,PUBLICATION
from resume_season_publication import retained_delivery
from mflix_client import Mflix

ROOT=Path('output/clone-feedback-20261021')
BANK=Path('output/drama-01/voice-bank.json')
SPECS=[
 ('laura-no-plain',2,['e02-18'],[7696],'NÃO!',1.0,'fearful','Correct Portuguese orthography; removes prior inline IPA.'),
 ('laura-no-breath',2,['e02-16'],[7696],'(gasps)Não!',1.0,'fearful','Correct orthography with documented gasp; not proof of a scream.'),
 ('father-como-natural',5,['e05-11'],[7700],'Como?',1.0,'surprised','Question punctuation without ellipsis.'),
 ('father-como-slower',5,['e05-11'],[7700],'Como?',.9,'surprised','Same question at 0.9 synthesis speed; no post acceleration.'),
 ('irina-sanctuary',32,['e32-7'],[7823],None,.9,'calm','Existing Irina clone at slower synthesis rate.'),
 ('irina-impossible',32,['e32-8'],[7823],None,.9,'surprised','Existing Irina clone at slower synthesis rate.'),
 ('irina-blood',32,['e32-9','e32-10'],[7823],None,.9,'fearful','Keep complete blood sentence connected; original fear direction.'),
 ('irina-threat',32,['e32-11','e32-12'],[7823],'Isso ainda não acabou!',.9,'angry','Connected threat without mechanical ellipsis; same words.'),
 ('irina-context',32,['e32-7','e32-8','e32-9','e32-10','e32-11','e32-12'],[7823],None,.9,'auto','Diagnostic continuous same-speaker passage. Auto is not verified emotional transfer or a production regrouping.')]


def expected_request(role,text,speed,emotion,bank):
 return {'projectId':59,'model':'speech-2.8-hd','text':text,'voiceId':bank[role]['voice_id'],
  'languageBoost':'Portuguese','emotion':emotion,'speed':speed,'vol':1,'pitch':0,'format':'wav',
  'language':None,'outputFormat':None,'duration':None,'prompt':None,'referenceVideoList':[]}


def validate(manifest,require_binding=True):
 if manifest['project_id']!=59 or manifest['review_project_id']!=148 or len(manifest['cases'])!=9:raise ValueError('Unexpected clone audition scope')
 if require_binding and read_json(ROOT/'manifest-fingerprint.json')['fingerprint']!=fingerprint(manifest):raise ValueError('Audition manifest is not bound')
 for path,sha in manifest['input_sha256'].items():
  if digest(Path(path))!=sha:raise ValueError('Bound audition input changed')
 bank=read_json(BANK)['voices'];seen=set()
 for case,spec in zip(manifest['cases'],SPECS):
  cid,n,cues,comment_ids,text,speed,emotion,hypothesis=spec
  if (case['id'],case['episode'],case['cue_ids'],case['comment_ids'],case['hypothesis'])!=(cid,n,cues,comment_ids,hypothesis):raise ValueError('Only fixed audition cases are allowed')
  units=case['source_units'];role=case['production_voice']
  if role not in ('Laura','Father','Irina') or any(u['production_voice']!=role for u in units):raise ValueError('Unexpected clone role')
  caption=' '.join(u['translation'] for u in units)
  if case['caption']!=caption:raise ValueError('Source caption changed')
  if text is None:text=(' <#0.35#> ' if len(units)>1 else ' ').join(u['translation'] for u in units)
  req=case['request']
  if req!=expected_request(role,text,speed,emotion,bank):raise ValueError('Request differs from fixed audition specification')
  if case['id'] in seen or not re.fullmatch('[a-z-]+',case['id']):raise ValueError('Invalid case ID')
  seen.add(case['id'])
  if (req['voiceId']!=bank[case['production_voice']]['voice_id'] or req['model']!='speech-2.8-hd'
   or req['projectId']!=59 or req['languageBoost']!='Portuguese' or req['speed'] not in (.9,1.0)
   or req['pitch']!=0 or req['vol']!=1 or req['format']!='wav'):raise ValueError('Existing clone or synthesis policy changed')
  cleaned=re.sub(r'\(gasps\)|<#\d+(?:\.\d+)?#>',' ',req['text'])
  words=lambda s:re.findall(r'\w+',s.casefold())
  if words(cleaned)!=words(case['caption']):raise ValueError('Synthesis words differ from reviewed Portuguese')
  for path,sha in case['baseline_files'].items():
   if digest(Path(path))!=sha:raise ValueError('Original baseline changed')


def prepare():
 bank=read_json(BANK)['voices'];available=candidates()
 feedback_path=Path('output/review-feedback/2026-10-21/comments-all.private.json')
 feedback=read_json(feedback_path);comments={c['commentId']:(r,c) for r in feedback['results'] for c in r['comments']}
 cases=[];inputs={str(BANK):digest(BANK),str(feedback_path):digest(feedback_path)}
 for cid,n,cues,comment_ids,text,speed,emotion,hypothesis in SPECS:
  folder=available[n];plan=read_json(folder/'plan.json');report=read_json(folder/'render-report.json')
  receipt_path=PUBLICATION/f'episode-{n:02}'/report['output_sha256']/'publication-result.json';receipt=read_json(receipt_path)
  retained_delivery(n,folder,receipt,receipt,receipt_path.parent/'candidate.json')
  units=[u for u in plan['units'] if any(c in cues for c in u['cue_ids'])]
  if [c for u in units for c in u['cue_ids']]!=cues or len({u['production_voice'] for u in units})!=1:raise ValueError('Cannot change source units or speaker boundaries')
  for comment_id in comment_ids:
   row,_=comments[comment_id]
   if row['episode']!=n or row['material']['assetId']!=receipt['asset_id']:raise ValueError('Feedback version differs')
  role=units[0]['production_voice'];caption=' '.join(u['translation'] for u in units)
  if text is None:text=(' <#0.35#> ' if len(units)>1 else ' ').join(u['translation'] for u in units)
  req=expected_request(role,text,speed,emotion,bank)
  baseline_units=[next(r for r in report['utterances'] if r['id']==u['id']) for u in units]
  if any(r['request']['voiceId']!=req['voiceId'] for r in baseline_units):raise ValueError('Do not substitute a different clone')
  baselines={r['fitted_path']:r['fitted_sha256'] for r in baseline_units}
  for path in [folder/'plan.json',folder/'reviewed.json',folder/'screenplay-context.json',folder/'render-report.json',receipt_path]:inputs[str(path)]=digest(path)
  cases.append({'id':cid,'episode':n,'cue_ids':cues,'comment_ids':comment_ids,'caption':caption,
   'production_voice':role,'source_speakers':[u.get('source_speaker','unknown') for u in units],
   'source_units':units,'start':units[0]['start'],'end':units[-1]['end'],
   'video_asset_id':receipt['asset_id'],'video_version':receipt['version'],
   'baseline_files':baselines,'request':req,'hypothesis':hypothesis,
   'location_status':'comment_phrase_candidate_not_human_confirmed','native_listening_passed':False})
 manifest={'project_id':59,'review_project_id':148,'cases':cases,'input_sha256':inputs,
  'new_clone_count':0,'native_listening_passed':False,'paid_request_limit':9,
  'policy':'A/B raw audition only. Correct existing clone IDs; no original SRT, plan, audio or picture replacement.'}
 validate(manifest,False);path=ROOT/'manifest.private.json'
 if path.exists() and fingerprint(read_json(path))!=fingerprint(manifest):raise ValueError('Existing manifest changed')
 bind(ROOT/'manifest-fingerprint.json',manifest)
 save_json(path,manifest);print('CLONE_MANIFEST_READY',len(cases),flush=True)


def synthesize(manifest,config,ffmpeg):
 validate(manifest);requests={};selected={};cache_report=[]
 legacy_roots={Path(f'output/drama-01/episode-{case["episode"]:02}') for case in manifest['cases']}|{ROOT/'requests'}
 for legacy in legacy_roots:
  for pending in legacy.rglob('*.submission-pending.json'):
   accepted=pending.with_name(pending.name.removesuffix('.submission-pending.json')+'.json')
   if not accepted.exists() or not read_json(accepted).get('taskId'):raise ValueError('Unknown earlier payment; reconcile instead of creating a new request')
 # Inspect every previous episode receipt/pending marker before any paid call.
 for case in manifest['cases']:
  request=case['request'];key=fingerprint(request)
  target=ROOT/'requests'/key
  matches=[]
  for prior in paid_cache_roots():
   found=paid_audio_folder(case['episode'],request,target,prior)
   if found!=target:matches.append(found)
  for marker in (Path(f'output/drama-01/episode-{case["episode"]:02}')).rglob('request-fingerprint.json'):
   if read_json(marker).get('fingerprint')==key:matches.append(marker.parent)
  found=matches[0] if matches else target
  if found!=target and (not (found/'audio-receipt.json').exists() or not (found/'original.wav').exists()):raise ValueError('Matching paid request incomplete; reconcile instead of resubmit')
  selected[key]=found;requests[key]=request
 client=None;results={}
 for key,request in requests.items():
  folder=selected[key];old=(folder/'submission.private.json').exists()
  if folder!=ROOT/'requests'/key or (folder/'audio-receipt.json').exists():
   path=folder/'original.wav';receipt=read_json(folder/'audio-receipt.json')
   accepted=read_json(folder/'submission.private.json')
   if (read_json(folder/'request-fingerprint.json')['fingerprint']!=key or receipt['sha256']!=digest(path)
    or receipt['task_id']!=accepted['taskId']):raise ValueError('Existing paid audio binding changed')
  else:
   if client is None:client=Mflix(config)
   path,receipt=generate(client,request,folder)
  # Never fit, cut speech, change pitch, or replace production audio in this stage.
  duration=len(read_audio(path,ffmpeg))/RATE
  results[key]={'path':str(path),'sha256':digest(path),'duration_seconds':duration,
   'request':request,'request_fingerprint':key,'task_id':receipt['task_id'],'prior_receipt_reused':old}
  save_json(ROOT/'generation-progress.private.json',results)
  print('CLONE_AUDIO_READY',key[:10],round(duration,3),'REUSED' if old else 'NEW',flush=True)
 save_json(ROOT/'generation-result.private.json',{'results':results,'new_clone_count':0,'native_listening_passed':False})


def render(manifest,ffmpeg):
 import numpy as np
 validate(manifest);generation=read_json(ROOT/'generation-result.private.json')['results']
 root=ROOT/'reel';root.mkdir(exist_ok=True);clips=[]
 for index,case in enumerate(manifest['cases'],1):
  key=fingerprint(case['request']);result=generation[key]
  if result['request']!=case['request'] or digest(result['path'])!=result['sha256']:raise ValueError('Generated candidate binding differs')
  original=[]
  for path in case['baseline_files']:
   if original:original.append(np.zeros(round(.35*RATE),dtype='float32'))
   original.append(read_audio(path,ffmpeg))
  baseline=root/f'{index:02}-baseline.wav';write_audio(baseline,np.concatenate(original))
  for label,audio in [('A - CURRENT FITTED',baseline),(f'B - NEW RAW (speed {case["request"]["speed"]})',Path(result['path']))]:
   suffix='a' if label.startswith('A') else 'b';name=f'{index:02}-{suffix}'
   duration=max(4,len(read_audio(audio,ffmpeg))/RATE+1)
   text=(f'{label} | {index:02}/{len(manifest["cases"])} | EP.{case["episode"]:02} | {case["production_voice"]}'
    f'\\N\\N{case["caption"]}\\N\\N{case["hypothesis"]}'
    '\\NExisting clone, unchanged voice ID | native review pending'
    '\\NA: current fitted dry voice | B: new raw dry voice'
    '\\NNo episode replacement; B timing and performance need review')
   ass=root/f'{name}.ass';ass.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n[V4+ Styles]\n'
    'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
    'Style: Default,Arial,30,&H00FFFFFF,&H00FFFFFF,&H00151A25,&H00151A25,0,0,0,0,100,100,0,0,1,1,0,5,60,60,40,1\n[Events]\n'
    'Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
    f'Dialogue: 0,0:00:00.00,0:10:00.00,Default,,0,0,0,,{text}\n',encoding='utf-8-sig')
   output=root/f'{name}.mp4'
   subprocess.run([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x151a25:s=1280x720:r=20',
    '-i',str(audio.resolve()),'-vf',f'ass={ass.name}','-af','adelay=500,apad','-t',str(duration),
    '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-b:a','128k',output.name],cwd=root,check=True,capture_output=True)
   clips.append({'case_id':case['id'],'label':label,'path':str(output),'duration_seconds':duration,
    'audio_path':str(audio),'audio_sha256':digest(audio),'request_fingerprint':key})
 listing=root/'concat.txt';listing.write_text(''.join(f"file '{Path(c['path']).name}'\n" for c in clips),encoding='utf-8')
 output=ROOT/'Carmilla_existing_clone_feedback_AB_v1.mp4'
 subprocess.run([str(ffmpeg),'-v','error','-y','-f','concat','-safe','0','-i',str(listing.resolve()),'-c','copy','-movflags','+faststart',str(output.resolve())],check=True,capture_output=True)
 report={'output_sha256':digest(output),'manifest_sha256':digest(ROOT/'manifest.private.json'),
  'generation_sha256':digest(ROOT/'generation-result.private.json'),'clips':clips,'case_count':len(manifest['cases']),
  'new_clone_count':0,'native_listening_passed':False,'episode_replaced':False,
  'baseline_kind':'Existing production-fitted dry voice; not original raw TTS',
  'duration_seconds':float(probe(output,ffmpeg)['format']['duration'])}
 save_json(ROOT/'reel-report.private.json',report);print('CLONE_AB_REEL_READY',len(clips),report['duration_seconds'],flush=True)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',choices=['prepare','generate','render'],required=True)
 p.add_argument('--mcp-config',type=Path);p.add_argument('--ffmpeg',type=Path);a=p.parse_args()
 if sys.platform!='win32':p.error('Business execution runs on Windows')
 ROOT.mkdir(parents=True,exist_ok=True)
 with process_lock(ROOT/'pilot.lock',timeout=0):
  if a.stage=='prepare':prepare();return
  manifest=read_json(ROOT/'manifest.private.json')
  if not a.ffmpeg:p.error('Existing FFmpeg required')
  if a.stage=='generate':
   if not a.mcp_config:p.error('Existing production MCP configuration required')
   synthesize(manifest,a.mcp_config,a.ffmpeg)
  else:render(manifest,a.ffmpeg)


if __name__=='__main__':main()
