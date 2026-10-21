"""Render a clearly labelled raw Gemini audition reel; never replaces episode footage."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import time
import wave
from process_lock import process_lock
from translate import read_json,save_json,fingerprint
from dub_episode import digest


def render(root,ffmpeg):
 manifest=read_json(root/'manifest.private.json');aliases=read_json(root/'samples/aliases.private.json')
 entries=[]
 for item in manifest['items']:
  sid=aliases.get(item['id'],{}).get('source_item_id',item['id'])
  folder=root/'samples'/sid;state=read_json(folder/'request-state.private.json');audio=folder/'gemini.wav'
  if state['status']!='completed' or digest(audio)!=state['audio_sha256']:raise ValueError('Audition audio incomplete')
  if sid!=item['id'] and fingerprint(state['request'])!=fingerprint(__import__('gemini_feedback_samples').payload(item)):raise ValueError('Alias request differs')
  with wave.open(str(audio),'rb') as wav:duration=wav.getnframes()/wav.getframerate()
  entries.append({'item':item,'source_item_id':sid,'audio_sha256':digest(audio),'duration_seconds':duration,
    'original_window_seconds':item['end']-item['start'],'within_original_window':duration<=item['end']-item['start'],
    'path':str(audio.resolve())})
 signature=fingerprint(entries);report_path=root/'audition-reel-report.private.json';output=root/'Carmilla_Gemini_pt-BR_feedback_audition_v1.mp4'
 if report_path.exists():
  old=read_json(report_path)
  if old['input_fingerprint']!=signature or digest(output)!=old['output_sha256']:raise ValueError('Prior reel changed')
  return output,old
 segments=root/'reel-segments';segments.mkdir(exist_ok=True)
 style=('ScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n[V4+ Styles]\n'
  'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
  'Style: Default,Arial,32,&H00FFFFFF,&H00FFFFFF,&H00151A25,&H00151A25,0,0,0,0,100,100,0,0,1,1,0,5,70,70,40,1\n\n[Events]\n'
  'Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n')
 reel_seconds=0
 for index,e in enumerate(entries,1):
  item=e['item'];duration=max(4,e['duration_seconds']+1)
  start=item['start'];stamp=f'{int(start//60):02}:{start%60:04.1f}'
  label=(f'{index:02}/{len(entries)} | EP.{item["episode"]:02} {stamp} | {item["production_character"]}'
   f'\\N\\N{item["text"]}\\N\\NGemini TTS | pt-BR | preset voice: {item["voice"]}'
   '\\NRaw voice audition - no BGM, no time fitting'
   '\\NNew voice differs from original actor; native review pending')
  if any(c in label for c in ('{','}')):raise ValueError('Unexpected subtitle markup')
  ass=segments/f'sample-{index:02}.ass';ass.write_text('[Script Info]\n'+style+f'Dialogue: 0,0:00:00.00,0:10:00.00,Default,,0,0,0,,{label}\n',encoding='utf-8-sig')
  dest=segments/f'sample-{index:02}.mp4'
  cmd=[str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x151a25:s=1280x720:r=20',
    '-i',e['path'],'-vf',f'ass={ass.name}', '-af','adelay=500,apad','-t',str(duration),
    '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-b:a','128k',dest.name]
  subprocess.run(cmd,cwd=segments,check=True,capture_output=True)
  e['reel_start_seconds']=reel_seconds;e['reel_duration_seconds']=duration;reel_seconds+=duration
 listing=segments/'concat.txt';listing.write_text(''.join(f"file 'sample-{i:02}.mp4'\n" for i in range(1,len(entries)+1)),encoding='utf-8')
 subprocess.run([str(ffmpeg),'-v','error','-y','-f','concat','-safe','0','-i',str(listing.resolve()),'-c','copy','-movflags','+faststart',str(output.resolve())],check=True,capture_output=True)
 report={'input_fingerprint':signature,'output_sha256':digest(output),'items':entries,'sample_cases':len(entries),
  'unique_generated_audio':len({e['source_item_id'] for e in entries}),'duration_seconds':reel_seconds,
  'cloning_performed':False,'native_listening_passed':False,'time_fitting_performed':False,
  'episode_video_modified':False,'picture':'New static labelled sample cards; no original footage edited.',
  'unaddressed_mix_comments':manifest['not_addressed_by_tts_comment_ids']}
 save_json(report_path,report);return output,report


def publish(root,path,report,config):
 from mflix_client import Mflix
 from publish_review import register,materials,check_matches
 import requests
 client=Mflix(config);upload_path=root/'reel-upload.private.json';sha=digest(path)
 if sha!=report['output_sha256']:raise ValueError('Reel changed before upload')
 if upload_path.exists():
  upload=read_json(upload_path)
  if upload['sha256']!=sha:raise ValueError('Prior upload differs')
 else:
  signed=client.call('createFilePresignedUrl',{'originalFileName':path.name})
  if not isinstance(signed,str) or not signed.startswith('https://'):raise ValueError('Expected HTTPS upload URL')
  upload={'sha256':sha,'signed_url':signed,'url':signed.split('?')[0],'status':'uploading'};save_json(upload_path,upload)
 if upload['status']!='uploaded':
  body=path.read_bytes()
  if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('Upload bytes changed')
  try:
   r=client.http.put(upload['signed_url'],data=body,timeout=120);r.raise_for_status()
  except requests.RequestException:raise RuntimeError('Reel upload failed; existing object checkpoint retained') from None
  upload['status']='uploaded';save_json(upload_path,upload)
 spec={'projectId':148,'gateType':'FINAL_CUT','name':f'Carmilla | Gemini pt-BR | Feedback audition v1 | {sha[:12]}',
  'url':upload['url'],'tags':['Carmilla','pt-BR','Gemini','audition'],'durationSeconds':round(report['duration_seconds']),
  'note':f'Gemini raw-voice audition: {report["sample_cases"]} located candidates, {report["unique_generated_audio"]} unique generated recordings. Preset voices differ from actors. Current reviewed pt-BR text retained. Static sample cards; no episode replacement, BGM repair or time fitting. Native accent and acting NOT approved. SHA256: {sha}'}
 ledger_path=root/'reel-review-ledger.private.json';ledger=read_json(ledger_path) if ledger_path.exists() else {'items':{}}
 asset=register(client,spec,ledger,ledger_path);row=check_matches(materials(client,148),spec)
 if row['assetId']!=asset or sha not in row.get('note',''):raise ValueError('Reel Review readback differs')
 try:
  r=requests.get(upload['url'],timeout=60);r.raise_for_status()
 except requests.RequestException:raise RuntimeError('Reel verification failed; receipts retained') from None
 if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('Downloaded reel differs')
 save_json(root/'reel-publication-result.private.json',{'project_id':148,'asset_id':asset,'name':spec['name'],
  'url':upload['url'],'sha256':sha,'verified_at':time.time()})
 print('GEMINI_REEL_REVIEW_VERIFIED',asset,flush=True)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);p.add_argument('--ffmpeg',required=True,type=Path)
 p.add_argument('--publish',action='store_true');p.add_argument('--mcp-config',type=Path);a=p.parse_args()
 if sys.platform!='win32':p.error('Render on Windows')
 if a.publish and not a.mcp_config:p.error('Review configuration required')
 with process_lock(a.root/'reel.lock',timeout=0):
  path,report=render(a.root,a.ffmpeg);print('GEMINI_REEL_READY',report['sample_cases'],report['unique_generated_audio'],flush=True)
  if a.publish:publish(a.root,path,report,a.mcp_config)


if __name__=='__main__':main()
