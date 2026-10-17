"""Transcribe disputed original English clips; produce evidence, never edit dialogue."""
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

from dub_episode import digest
from process_lock import process_lock
from rerun_carmilla_season import sources
from translate import fingerprint,read_json,save_json

ROOT=Path('output/carmilla-source-verification-20261017')


def disputed():
    result=[]
    root=Path('output/carmilla-season-revision-20261017-retry1')
    for n in range(1,33):
        p=root/f'episode-{n:02}'/'reviewed.json'
        if not p.exists():continue
        review=read_json(p);plan_path,source_path,_=sources(n)
        plan=read_json(plan_path);rows={r['id']:r for r in read_json(source_path)['segments']}
        for c in review['cues']:
            errors=[i['reason'] for i in c['issues'] if i['severity']=='error']
            if errors:result.append({'episode':n,'cue':rows[c['id']],'issues':errors,
                                    'source_audio':plan['assets']['source_audio'],
                                    'review_sha256':digest(p),'source_sha256':digest(source_path)})
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--ffmpeg',required=True,type=Path)
    p.add_argument('--models',nargs='+',default=['small.en','medium.en'],choices=['small.en','medium.en'])
    a=p.parse_args()
    if sys.platform!='win32':p.error('Original media analysis stays on Windows')
    from faster_whisper import WhisperModel
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'source-verification.lock',timeout=0):
        todo=disputed();save_json(ROOT/'input.json',todo)
        sha= fingerprint(todo)
        marker=ROOT/'input-fingerprint.json'
        if marker.exists() and read_json(marker)['fingerprint']!=sha:raise ValueError('Source verification inputs changed')
        save_json(marker,{'fingerprint':sha})
        for model_name in a.models:
            local=Path('output/tools/source-asr-models')/model_name
            local_model=(local/'verified.json').exists()
            model=WhisperModel(str(local.resolve()) if local_model else model_name,device='cpu',compute_type='int8',cpu_threads=8,num_workers=1,
                              download_root=str(Path('output/tools/whisper-models').resolve()))
            model_files={str(p):digest(p) for p in (local if local_model else Path('output/tools/whisper-models')).rglob('*')
                         if p.is_file() and any(s in str(p) for s in [f'whisper-{model_name}',f'whisper-{model_name.replace(".en","")}'])
                         and p.name in ('model.bin','config.json','tokenizer.json')}
            if local_model:
                model_files={str(local/p):digest(local/p) for p in ['model.bin','config.json','tokenizer.json'] if (local/p).exists()}
            for item in todo:
                cue=item['cue'];folder=ROOT/f'episode-{item["episode"]:02}'/cue['id'];folder.mkdir(parents=True,exist_ok=True)
                result_path=folder/f'{model_name}.json'
                source=Path(item['source_audio']);source_sha=digest(source)
                clip=folder/'original-context.wav'
                start=max(0,cue['start']-1.0);end=cue['end']+1.0
                if not clip.exists():
                    subprocess.run([str(a.ffmpeg),'-v','error','-n','-ss',str(start),'-to',str(end),'-i',str(source),
                                    '-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(clip)],check=True)
                signature={'source_audio_sha256':source_sha,'cue':cue,'clip_sha256':digest(clip),
                           'padding_seconds':1.0,'model':model_name,'model_files':model_files,
                           'faster_whisper_version':version('faster-whisper'),'source_review_sha256':item['review_sha256']}
                if result_path.exists():
                    if read_json(result_path)['input']!=signature:raise ValueError('ASR evidence changed')
                    continue
                segments,info=model.transcribe(str(clip),language='en',beam_size=5,temperature=0,
                                               condition_on_previous_text=False,word_timestamps=True,vad_filter=False)
                rows=[{'start':s.start+start,'end':s.end+start,'text':s.text,'avg_logprob':s.avg_logprob,
                       'no_speech_prob':s.no_speech_prob,'words':[{'word':w.word,'start':w.start+start,
                         'end':w.end+start,'probability':w.probability} for w in (s.words or [])]} for s in segments]
                if digest(source)!=source_sha:raise ValueError('Source audio changed')
                save_json(result_path,{'input':signature,'segments':rows,'human_listened':False,
                    'source_speaker_verified':False,'authority':'ASR evidence only; do not silently rewrite original subtitles'})
                print('SOURCE_TRANSCRIBED',model_name,item['episode'],cue['id'],flush=True)
                save_json(ROOT/'progress.json',{'model':model_name,'episode':item['episode'],'cue_id':cue['id'],
                                              'stage':'transcribing','total_disputed_cues':len(todo)})
            del model
        save_json(ROOT/'progress.json',{'stage':'transcribed_evidence','total_disputed_cues':len(todo),
                                       'models':a.models,'human_listened':False})


if __name__=='__main__':main()
