"""Local content screening for existing-clone auditions; not native listening."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from translate import read_json,save_json,fingerprint
from dub_episode import digest
from process_lock import process_lock


def main():
 p=argparse.ArgumentParser();p.add_argument('--ffmpeg',required=True,type=Path);a=p.parse_args()
 if sys.platform!='win32':p.error('Run screening on Windows')
 from faster_whisper import WhisperModel
 import numpy as np
 from clone_feedback_pilot import ROOT,validate
 manifest=read_json(ROOT/'manifest.private.json');validate(manifest)
 generated=read_json(ROOT/'generation-result.private.json')['results']
 local=Path('output/tools/source-asr-models/large-v3');verified=read_json(local/'verified.json');official=read_json(local/'official-source.json')
 if verified.get('repo')!='Systran/faster-whisper-large-v3' or verified.get('official_hashes_verified') is not True or verified.get('revision')!=official['revision']:raise ValueError('Pinned official ASR required')
 expected=next(f['lfs']['sha256'] for f in official['siblings'] if f['rfilename']=='model.bin')
 if digest(local/'model.bin')!=expected:raise ValueError('ASR binary changed')
 decoding={'language':'pt','beam_size':5,'temperature':0,'condition_on_previous_text':False,'vad_filter':False}
 with process_lock(ROOT/'screening.lock',timeout=0):
  model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
  rows=[];out=ROOT/'content-screening';out.mkdir(exist_ok=True)
  for case in manifest['cases']:
   key=fingerprint(case['request']);r=generated[key];target=out/f'{key}.private.json'
   if r['request']!=case['request'] or digest(r['path'])!=r['sha256']:raise ValueError('Audition input changed')
   if target.exists():
    record=read_json(target)
    if record['audio_sha256']!=r['sha256'] or record['decoding']!=decoding:raise ValueError('Prior screening basis differs')
   else:
    audio=subprocess.run([str(a.ffmpeg),'-v','error','-i',r['path'],'-f','f32le','-ar','16000','-ac','1','pipe:1'],check=True,capture_output=True)
    segments,_=model.transcribe(np.frombuffer(audio.stdout,dtype='<f4'),**decoding)
    record={'case_id':case['id'],'request_fingerprint':key,'audio_sha256':r['sha256'],'expected_text':case['caption'],
     'asr_transcript':' '.join(s.text.strip() for s in segments),'decoding':decoding,
     'native_listening_passed':False,'model_revision':verified['revision']}
    save_json(target,record)
   rows.append(record);print('CLONE_CONTENT_SCREENED',case['id'],flush=True)
  save_json(ROOT/'content-screening.private.json',{'results':rows,'native_listening_passed':False})


if __name__=='__main__':main()
