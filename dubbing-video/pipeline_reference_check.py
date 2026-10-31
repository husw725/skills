"""Offline content screening for prepared English role references; never identity/native approval."""
import argparse
from pathlib import Path
import sys
from dub_episode import digest
from translate import read_json,save_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role-folder',type=Path,action='append',required=True)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows offline reference screening only')
    model_path=Path('output/tools/source-asr-models/large-v3')
    official=read_json(model_path/'official-source.json');verified=read_json(model_path/'verified.json')
    expected=next(x['lfs']['sha256'] for x in official['siblings'] if x['rfilename']=='model.bin')
    if verified.get('official_hashes_verified') is not True or digest(model_path/'model.bin')!=expected:
        raise ValueError('Offline model weights changed')
    from faster_whisper import WhisperModel
    model=None
    for folder in args.role_folder:
        wav=folder/'reference.wav';receipt=read_json(folder/'reference-receipt.private.json')
        if digest(wav)!=receipt['sha256']:raise ValueError('Prepared reference changed')
        report=folder/'reference-asr.private.json'
        if report.exists():
            old=read_json(report)
            if old['reference_sha256']!=receipt['sha256'] or old['model_sha256']!=expected:raise ValueError('ASR cache binding changed')
            continue
        if model is None:model=WhisperModel(str(model_path),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
        segments,info=model.transcribe(str(wav),language='en',beam_size=5,temperature=0,
            condition_on_previous_text=False,vad_filter=False,word_timestamps=True)
        rows=[{'start':s.start,'end':s.end,'text':s.text,'no_speech_prob':s.no_speech_prob,
               'words':[{'word':w.word,'start':w.start,'end':w.end,'probability':w.probability} for w in s.words or []]} for s in segments]
        save_json(report,{'reference_sha256':receipt['sha256'],'model_sha256':expected,'segments':rows,
                         'source_speaker_audio_verified':False,'native_listening_passed':False,
                         'screening_not_listening_approval':True})
        print('REFERENCE_CONTENT_SCREENED',folder.name,flush=True)


if __name__=='__main__':main()
