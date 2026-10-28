"""Read-only source timing evidence, never a speaker or native-accent verdict."""
from pathlib import Path
import subprocess
import json
import numpy as np
from faster_whisper import WhisperModel
from translate import read_json, save_json
from dub_episode import digest

ROOT=Path('output/feedback-repair-20261028')
if __name__=='__main__':
    packet=read_json(ROOT/'source-packet.private.json')
    ffmpeg=r'D:\Program Files\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe'
    local=Path('output/tools/source-asr-models/large-v3')
    official=read_json(local/'official-source.json');verified=read_json(local/'verified.json')
    sha=next(x['lfs']['sha256'] for x in official['siblings'] if x['rfilename']=='model.bin')
    if digest(local/'model.bin')!=sha or verified['revision']!=official['revision']:
        raise ValueError('Pinned official ASR required')
    model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
    source=packet['32']['plan']['assets']['source_audio']
    raw=subprocess.run([ffmpeg,'-v','error','-i',source,'-t','25','-f','f32le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True)
    segments,_=model.transcribe(np.frombuffer(raw.stdout,dtype='<f4'),language='en',beam_size=5,
      temperature=0,condition_on_previous_text=False,vad_filter=False,word_timestamps=True)
    rows=[]
    for s in segments:
        rows.append({'start':s.start,'end':s.end,'text':s.text,'words':[
          {'start':w.start,'end':w.end,'word':w.word,'probability':w.probability} for w in s.words]})
    report={'source_sha256':digest(source),'packet_sha256':digest(ROOT/'source-packet.private.json'),
      'model_revision':verified['revision'],'segments':rows,
      'policy':'Machine timing leads only; compare frames and source before editorial correction; not speaker verification.'}
    save_json(ROOT/'ep32-source-timing.private.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    checks=[]
    for start,end in [(7,13.1),(13,17),(16,23)]:
        raw=subprocess.run([ffmpeg,'-v','error','-ss',str(start),'-i',packet['32']['plan']['assets']['video'],
          '-t',str(end-start),'-f','f32le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True)
        segments,_=model.transcribe(np.frombuffer(raw.stdout,dtype='<f4'),language='en',beam_size=5,
          temperature=0,condition_on_previous_text=False,vad_filter=False,word_timestamps=True)
        checks.append({'source_start':start,'source_end':end,'source':'original video audio',
          'segments':[{'start':start+s.start,'end':start+s.end,'text':s.text} for s in segments]})
    save_json(ROOT/'ep32-original-video-crosscheck.private.json',checks)
    print(json.dumps(checks,ensure_ascii=False),flush=True)
