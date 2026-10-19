"""Additional local, unprompted ASR evidence; no translation or production writes."""
import argparse
from importlib.metadata import version
from pathlib import Path
import subprocess,sys,time,wave

from cartesia_pilot import bind
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json
from verify_carmilla_source import disputed

ROOT=Path('output/carmilla-source-large-20261019')
IDS={'e05-7','e08-6','e27-12','e27-2','e29-8','e29-19'}
DECODING={'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':False,
          'word_timestamps':True,'vad_filter':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ffmpeg',required=True,type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Source media and ASR execution remain on Windows')
    from faster_whisper import WhisperModel
    import numpy as np
    local=Path('output/tools/source-asr-models/large-v3')
    verified=read_json(local/'verified.json');official=read_json(local/'official-source.json')
    if (verified.get('repo')!='Systran/faster-whisper-large-v3'
            or verified.get('official_hashes_verified') is not True
            or verified.get('revision')!=official['revision']):raise ValueError('Verified pinned official model required')
    model_files={str(local/f):digest(local/f) for f in ('model.bin','config.json','tokenizer.json','preprocessor_config.json')}
    expected=next(f['lfs']['sha256'] for f in official['siblings'] if f['rfilename']=='model.bin')
    if model_files[str(local/'model.bin')]!=expected:raise ValueError('Model binary changed')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'source.lock',timeout=0):
        todo=[r for r in disputed() if r['cue']['id'] in IDS]
        if {r['cue']['id'] for r in todo}!=IDS:raise ValueError('Disputed source scope changed')
        bind(ROOT/'input-fingerprint.json',{'items':todo,'model_files':model_files,'decoding':DECODING})
        model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
        for item in todo:
            cue=item['cue'];source=Path(item['source_audio']);source_sha=digest(source)
            for label,padding in [('context',2.0),('tight',.25)]:
                start=max(0,cue['start']-padding);end=cue['end']+padding
                folder=ROOT/f'episode-{item["episode"]:02}'/cue['id']/label;folder.mkdir(parents=True,exist_ok=True)
                clip=folder/'original.wav';marker=folder/'clip-input.json'
                if clip.exists() and not marker.exists():raise ValueError('Unbound diagnostic clip')
                bind(marker,{'source_sha256':source_sha,'start':start,'end':end,'channels':1,'sample_rate':16000})
                if not clip.exists():subprocess.run([str(a.ffmpeg),'-v','error','-n','-ss',str(start),'-to',str(end),
                    '-i',str(source),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(clip)],check=True)
                spec={'cue':cue,'source_audio_sha256':source_sha,'clip_sha256':digest(clip),'clip_start':start,'clip_end':end,
                      'model':'large-v3','model_revision':verified['revision'],'model_files':model_files,
                      'source_review_sha256':item['review_sha256'],'faster_whisper_version':version('faster-whisper'),
                      'decoding':DECODING,'method':'unprompted-local-large-v3-'+label}
                spec['inference']={'device':'cpu','compute_type':'int8','cpu_threads':8,'num_workers':1}
                spec['official_metadata_sha256']=digest(local/'official-source.json')
                target=folder/'large-v3.json'
                if target.exists():
                    if read_json(target)['input']!=spec:raise ValueError('Diagnostic input changed')
                    continue
                with wave.open(str(clip),'rb') as wav:
                    if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('Unexpected PCM')
                    samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
                segments,_=model.transcribe(samples,**DECODING)
                rows=[{'start':s.start+start,'end':s.end+start,'text':s.text,'avg_logprob':s.avg_logprob,
                    'no_speech_prob':s.no_speech_prob,'words':[{'word':w.word,'start':w.start+start,
                        'end':w.end+start,'probability':w.probability} for w in (s.words or [])]} for s in segments]
                if digest(source)!=source_sha:raise ValueError('Source changed during recognition')
                save_json(target,{'input':spec,'segments':rows,'human_listened':False,'source_speaker_verified':False})
                save_json(ROOT/'progress.json',{'stage':'transcribing','cue':cue['id'],'window':label,'updated_at':time.time()})
        save_json(ROOT/'progress.json',{'stage':'evidence_ready','finished_at':time.time(),'cues':len(todo),
                                      'human_listened':False,'production_modified':False})


if __name__=='__main__':main()
