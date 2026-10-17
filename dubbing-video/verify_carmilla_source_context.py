"""Unprompted whole-episode ASR context, preserving previous disputed-clip evidence."""
import argparse
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path
import subprocess,sys

from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json,fingerprint
from verify_carmilla_source import disputed,ROOT

METHOD='unprompted-full-episode-vad-v1'
DECODING={'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':True,
          'word_timestamps':True,'vad_filter':True,
          'vad_parameters':{'min_silence_duration_ms':200,'speech_pad_ms':200}}


def main():
    p=argparse.ArgumentParser();p.add_argument('--ffmpeg',required=True,type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Original media stays on Windows')
    from faster_whisper import WhisperModel
    import numpy as np
    with process_lock(ROOT/'source-verification.lock',timeout=0):
        todo=disputed()
        if read_json(ROOT/'input-fingerprint.json')['fingerprint']!=fingerprint(todo):
            raise ValueError('Original source evidence input changed')
        by_episode=defaultdict(list)
        for item in todo:by_episode[item['episode']].append(item)
        for model_name in ('small.en','medium.en'):
            local=Path('output/tools/source-asr-models')/model_name
            if not read_json(local/'verified.json')['official_hashes_verified']:raise ValueError('Verified local model required')
            model_files={str(local/name):digest(local/name) for name in ['model.bin','config.json','tokenizer.json']}
            model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
            for n,items in sorted(by_episode.items()):
                source=Path(items[0]['source_audio']);source_sha=digest(source)
                if any(item['source_audio']!=str(source) for item in items):raise ValueError('Episode source mismatch')
                full=ROOT/f'episode-{n:02}'/f'{model_name}.context-full.json'
                spec={'method':METHOD,'source_audio_sha256':source_sha,'model':model_name,
                      'model_files':model_files,'faster_whisper_version':version('faster-whisper'),'decoding':DECODING}
                if full.exists():
                    data=read_json(full)
                    if data['input']!=spec:raise ValueError('Whole-episode evidence provenance changed')
                else:
                    # FFmpeg decodes directly to a local float array. No remote
                    # upload and no transcript/script prompt to bias recognition.
                    decoded=subprocess.run([str(a.ffmpeg),'-v','error','-i',str(source),'-vn','-ac','1',
                        '-ar','16000','-f','f32le','-'],capture_output=True,check=True).stdout
                    samples=np.frombuffer(decoded,dtype='<f4')
                    segments,_=model.transcribe(samples,**DECODING)
                    rows=[{'start':s.start,'end':s.end,'text':s.text,'avg_logprob':s.avg_logprob,
                        'no_speech_prob':s.no_speech_prob,'words':[{'word':w.word,'start':w.start,
                          'end':w.end,'probability':w.probability} for w in (s.words or [])]} for s in segments]
                    if digest(source)!=source_sha:raise ValueError('Source audio changed during ASR')
                    data={'input':spec,'segments':rows,'human_listened':False,'source_speaker_verified':False}
                    save_json(full,data)
                for item in items:
                    cue=item['cue'];folder=ROOT/f'episode-{n:02}'/cue['id'];clip=folder/'original-context.wav'
                    original=read_json(folder/f'{model_name}.json')['input']
                    if original['source_audio_sha256']!=source_sha or original['cue']!=cue or original['clip_sha256']!=digest(clip):
                        raise ValueError('Original clip provenance changed')
                    signature={**original,'method':METHOD,'decoding':DECODING,
                        'model_files':model_files,'whole_episode_evidence':str(full),'whole_episode_sha256':digest(full)}
                    rows=[s for s in data['segments'] if s['end']>=cue['start']-1 and s['start']<=cue['end']+1]
                    target=folder/f'{model_name}.context.json'
                    record={'input':signature,'segments':rows,'human_listened':False,'source_speaker_verified':False}
                    if target.exists() and read_json(target)!=record:raise ValueError('Context evidence changed')
                    if not target.exists():save_json(target,record)
                    print('SOURCE_CONTEXT_TRANSCRIBED',model_name,n,cue['id'],flush=True)
            del model


if __name__=='__main__':main()
