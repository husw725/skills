"""Local ASR content screening only; never certifies native accent or acting."""
import argparse
from pathlib import Path
import sys
from translate import read_json,save_json
from dub_episode import digest
from process_lock import process_lock


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);a=p.parse_args()
 if sys.platform!='win32':p.error('Local audio screening runs on Windows')
 from faster_whisper import WhisperModel
 local=Path('output/tools/source-asr-models/large-v3');verified=read_json(local/'verified.json');official=read_json(local/'official-source.json')
 if verified.get('repo')!='Systran/faster-whisper-large-v3' or verified.get('official_hashes_verified') is not True or verified.get('revision')!=official['revision']:raise ValueError('Pinned local ASR model required')
 expected=next(f['lfs']['sha256'] for f in official['siblings'] if f['rfilename']=='model.bin')
 if digest(local/'model.bin')!=expected:raise ValueError('ASR model binary changed')
 decoding={'language':'pt','beam_size':5,'temperature':0,'condition_on_previous_text':False,'vad_filter':False}
 with process_lock(a.root/'asr-screening.lock',timeout=0):
  model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
  rows=[]
  for state_path in sorted((a.root/'samples').glob('*/request-state.private.json')):
   state=read_json(state_path);audio=state_path.parent/'gemini.wav'
   if state['status']!='completed' or digest(audio)!=state['audio_sha256']:raise ValueError('Incomplete generated sample')
   target=state_path.parent/'asr-screening.private.json'
   if target.exists():
    result=read_json(target)
    if result['audio_sha256']!=state['audio_sha256'] or result['decoding']!=decoding:raise ValueError('Prior ASR binding changed')
   else:
    # Whisper takes 16kHz floats; use its audio decoder to preserve correct resampling.
    from faster_whisper.audio import decode_audio
    data=decode_audio(str(audio),sampling_rate=16000)
    segments,_=model.transcribe(data,**decoding);transcript=' '.join(s.text.strip() for s in segments)
    result={'item_id':state['item']['id'],'audio_sha256':state['audio_sha256'],'expected_text':state['item']['text'],
     'asr_transcript':transcript,'decoding':decoding,'model_revision':verified['revision'],
     'native_listening_passed':False,'meaning_or_pronunciation_acceptance':False}
    save_json(target,result)
   rows.append(result)
   print('ASR_SAMPLE_SCREENED',result['item_id'],flush=True)
  save_json(a.root/'asr-screening.private.json',{'results':rows,'native_listening_passed':False})


if __name__=='__main__':main()
