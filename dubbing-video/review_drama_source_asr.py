"""Local English timing drafts for the six first-episode reference variants.

Machine transcription is evidence for source matching, never original subtitles,
speaker verification, approved screenplay context or permission to synthesize.
"""
from pathlib import Path
import re
import sys
import time
import unicodedata
import wave
import numpy as np
from translate import read_json,save_json,write_srt,fingerprint
from dub_episode import digest
from process_lock import process_lock
from review_drama_intake import validate_manifest

ROOT=Path('output/four-dramas-20261030')
SOURCE_IDS={96:{622},110:{706,1667},102:{1255},100:{1456,1518}}


def norm(text):return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',text).casefold()))


def main():
    if sys.platform!='win32':raise ValueError('Run source materials on Windows')
    from faster_whisper import WhisperModel
    with process_lock(ROOT/'source-asr.lock',timeout=0):
        manifest=read_json(ROOT/'intake-manifest.private.json');validate_manifest(manifest)
        local=Path('output/tools/source-asr-models/large-v3');official=read_json(local/'official-source.json');verified=read_json(local/'verified.json')
        model_sha=next(x['lfs']['sha256'] for x in official['siblings'] if x['rfilename']=='model.bin')
        if (verified.get('official_hashes_verified') is not True or verified['revision']!=official['revision']
          or verified['repo']!='Systran/faster-whisper-large-v3' or digest(local/'model.bin')!=model_sha):raise ValueError('Pinned ASR source required')
        model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
        decode={'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':False,'vad_filter':False,'word_timestamps':True}
        state={'stage':'transcribing_reference_variants','completed':[],'errors':{},'formal_translation_ready':False,'updated_at':time.time()}
        save_json(ROOT/'source-asr-progress.private.json',state)
        for pid,ids in SOURCE_IDS.items():
            for aid in sorted(ids):
                item=next(x for x in manifest['items'] if x['project_id']==pid and x['kind']=='video' and x['asset_id']==aid)
                prep=Path('output')/f'review-project-{pid}'/'source-preparation'
                inspection=read_json(prep/f'asset-{aid}-v{item["version"]}.private.json')
                source=Path(inspection['source_asset']['path']);audio=prep/f'asset-{aid}-source-16k.wav'
                if digest(source)!=inspection['source_sha256'] or digest(audio)!=inspection['derived_sha256'][str(audio)]:raise ValueError('Reference changed')
                target=Path('output')/f'review-project-{pid}'/'asr-draft'/f'asset-{aid}-v{item["version"]}';target.mkdir(parents=True,exist_ok=True)
                binding={'source_video_sha256':digest(source),'audio_sha256':digest(audio),'model_revision':verified['revision'],'decoding':decode}
                result_path=target/'source-en-draft.private.json'
                if result_path.exists():
                    report=read_json(result_path)
                    if report['binding']!=binding:raise ValueError('ASR checkpoint basis changed')
                else:
                    with wave.open(str(audio),'rb') as w:
                        if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):raise ValueError('Expected prepared 16k PCM source')
                        samples=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype('float32')/32768
                    segments,_=model.transcribe(samples,**decode);rows=[]
                    for i,s in enumerate(segments,1):
                        rows.append({'id':f'p{pid}-a{aid}-{i}','episode':str(item['episode']),'start':s.start,'end':s.end,'text':s.text.strip(),
                          'avg_logprob':s.avg_logprob,'no_speech_prob':s.no_speech_prob,'words':[
                            {'word':w.word,'start':w.start,'end':w.end,'probability':w.probability} for w in s.words or []]})
                    comparisons=[]
                    for script in manifest['items']:
                        if script['project_id']!=pid or script['kind']!='document' or script.get('script_classification')=='derived_excerpt_not_full_script':continue
                        path=prep/f'asset-{script["asset_id"]}-v{script["version"]}.txt'
                        if not path.exists():continue
                        text=norm(path.read_text(encoding='utf-8'));eligible=[r for r in rows if len(norm(r['text']).split())>=4]
                        comparisons.append({'script_asset_id':script['asset_id'],'script_text_sha256':digest(path),
                          'eligible_segments':len(eligible),'literal_match_segments':[r['id'] for r in eligible if norm(r['text']) in text],
                          'status':'heuristic_source_evidence_only_not_semantic_approval'})
                    report={'binding':binding,'project_id':pid,'asset_id':aid,'variant':item['variant'],'segments':rows,
                      'script_comparisons':comparisons,'source_subtitles_available':False,'source_speaker_verified':False,
                      'per_cue_screenplay_reviewed':False,'formal_translation_ready':False,'native_listening_passed':False}
                    save_json(result_path,report)
                    write_srt(target/'source-en-draft.srt',[{**r,'translation':r['text']} for r in rows])
                state['completed'].append({'project_id':pid,'asset_id':aid,'report':str(result_path),'sha256':digest(result_path)})
                state['updated_at']=time.time();save_json(ROOT/'source-asr-progress.private.json',state)
        state.update(stage='source_timing_drafts_ready_review_pending',finished_at=time.time());save_json(ROOT/'source-asr-progress.private.json',state)


if __name__=='__main__':
    log=ROOT/'source-asr.log';sys.stdout=log.open('a',encoding='utf-8',buffering=1);sys.stderr=sys.stdout
    try:main()
    except Exception as exc:
        path=ROOT/'source-asr-progress.private.json'
        state=read_json(path) if path.exists() else {}
        save_json(path,{**state,'stage':'failed_needs_review','error_type':type(exc).__name__,'updated_at':time.time()})
        raise
