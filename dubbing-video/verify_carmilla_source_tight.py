"""Additional unprompted local ASR with short padding; preserve all old evidence."""
import argparse
from importlib.metadata import version
from pathlib import Path
import subprocess,sys,wave,time

from dub_episode import digest
from process_lock import process_lock
from translate import fingerprint,read_json,save_json
from verify_carmilla_source import disputed

ROOT=Path('output/carmilla-source-tight-20261017')
EPISODES={4,5,6,8,12,20,27,29}
METHOD='unprompted-cue-tight-v1'
DECODING={'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':False,
          'word_timestamps':True,'vad_filter':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ffmpeg',required=True,type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Source media remains on Windows')
    from faster_whisper import WhisperModel
    import numpy as np
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'source.lock',timeout=0):
        todo=[row for row in disputed() if row['episode'] in EPISODES]
        marker=ROOT/'input-fingerprint.json';sha=fingerprint(todo)
        if marker.exists() and read_json(marker)['fingerprint']!=sha:raise ValueError('Tight evidence input changed')
        save_json(marker,{'fingerprint':sha})
        for name in ('small.en','medium.en'):
            local=Path('output/tools/source-asr-models')/name
            if not read_json(local/'verified.json')['official_hashes_verified']:raise ValueError('Verified official weights required')
            model_files={str(local/f):digest(local/f) for f in ('model.bin','config.json','tokenizer.json')}
            model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
            for item in todo:
                cue=item['cue'];source=Path(item['source_audio']);source_sha=digest(source)
                folder=ROOT/f'episode-{item["episode"]:02}'/cue['id'];folder.mkdir(parents=True,exist_ok=True)
                clip=folder/'original-tight.wav';start=max(0,cue['start']-.15);end=cue['end']+.15
                if not clip.exists():
                    subprocess.run([str(a.ffmpeg),'-v','error','-n','-ss',str(start),'-to',str(end),'-i',str(source),
                        '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(clip)],check=True)
                spec={'method':METHOD,'cue':cue,'source_audio_sha256':source_sha,'clip_sha256':digest(clip),
                      'padding_seconds':.15,'clip_start':start,'clip_end':end,'model':name,'model_files':model_files,
                      'source_review_sha256':item['review_sha256'],'faster_whisper_version':version('faster-whisper'),
                      'decoding':DECODING}
                target=folder/(name+'.json')
                if target.exists():
                    if read_json(target)['input']!=spec:raise ValueError('Tight evidence provenance changed')
                    continue
                with wave.open(str(clip),'rb') as wav:
                    if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('Unexpected PCM')
                    samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
                segments,_=model.transcribe(samples,**DECODING)
                rows=[{'start':s.start+start,'end':s.end+start,'text':s.text,'avg_logprob':s.avg_logprob,
                    'no_speech_prob':s.no_speech_prob,'words':[{'word':w.word,'start':w.start+start,
                        'end':w.end+start,'probability':w.probability} for w in (s.words or [])]} for s in segments]
                if digest(source)!=source_sha:raise ValueError('Source changed during ASR')
                save_json(target,{'input':spec,'segments':rows,'human_listened':False,'source_speaker_verified':False})
                save_json(ROOT/'progress.json',{'stage':'transcribing','model':name,'cue':cue['id'],'updated_at':time.time()})
                print('TIGHT_TRANSCRIBED',name,item['episode'],cue['id'],flush=True)
            del model
        save_json(ROOT/'progress.json',{'stage':'evidence_ready','finished_at':time.time(),
            'human_listened':False,'source_speaker_verified':False,'total_cues':len(todo)})


if __name__=='__main__':main()
