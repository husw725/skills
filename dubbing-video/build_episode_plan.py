"""Prepare the next episode's assets and reviewed translation for ordered production."""
import argparse
from pathlib import Path
import subprocess
import sys

from translate import fingerprint,read_json,save_json


def apply_casting(units,bank,path):
    """Explicit production casting preserves unknown source identity and reuses only existing voices."""
    if not path.exists():return {}
    casting=read_json(path)
    if casting.get('units_fingerprint')!=fingerprint(units):
        raise ValueError('Production casting inputs changed; review assignments again')
    assignments=casting.get('assignments',{})
    known={cue for unit in units for cue in unit['cue_ids']}
    if set(assignments)-known:raise ValueError('Casting references absent source cues')
    selected={}
    for unit in units:
        choices=[assignments.get(cue) for cue in unit['cue_ids']]
        if not any(choices):continue
        if unit['speaker']!='unknown' or not all(choices) or any(c!=choices[0] for c in choices):
            raise ValueError('Casting must cover a complete unknown-speaker unit consistently')
        choice=choices[0]
        if choice.get('voice') not in bank['voices'] or not choice.get('reason'):
            raise ValueError('Casting requires an existing reusable voice and decision evidence')
        selected[unit['id']]=choice['voice']
        unit['production_casting']={**choice,'source_speaker_verified':False}
    return selected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episode',required=True,type=int);p.add_argument('--ffmpeg',required=True,type=Path)
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business execution is Windows-only')
    episode=args.episode;folder=Path(f'output/drama-01/episode-{episode:02d}')
    source=Path(f'input/drama-01/episode-{episode:02d}')
    files=list(source.iterdir())
    def unique(test):
        matches=[f for f in files if f.is_file() and test(f)]
        if len(matches)!=1:raise ValueError('Missing or ambiguous episode asset')
        return matches[0]
    video=unique(lambda f:f.suffix.lower()=='.mp4')
    bgm=unique(lambda f:f.name.lower().endswith('_bgm.wav'))
    sfx=unique(lambda f:f.name.lower().endswith('_sfx.wav'))
    media=folder/'media';subprocess.run([sys.executable,'prepare_media.py','--video',str(video),'--bgm',str(bgm),
       '--sfx',str(sfx),'--output-dir',str(media),'--ffmpeg',str(args.ffmpeg)],check=True)
    data=read_json(folder/'translation/speech-units.draft.json');units=data['units'];voices={}
    bank_path=Path('output/drama-01/voice-bank.json');bank=read_json(bank_path)
    casting=apply_casting(units,bank,folder/'production-casting.json')
    for unit in units:
        name=casting.get(unit['id']) or (unit['speaker'] if unit['speaker']!='unknown' else f'Narrator_EP{episode:02d}')
        name={'Camila':'Carmilla','Camilla':'Carmilla','Kamila':'Carmilla'}.get(name,name)
        unit['production_voice']=name
        annotations=[a for a in unit.get('screenplay_annotations',[]) if a]
        emotion=annotations[0].get('emotion_intent','calm') if annotations else 'calm'
        unit['emotion']=emotion if emotion in ('auto','happy','sad','angry','fearful','disgusted','surprised','calm','fluent','whisper') else 'calm'
        unit['speed']=1.05;voices.setdefault(name,{})
    manifest=read_json(media/'media-manifest.json')
    plan={'project_id':59,'episode':episode,'assets':{'video':str(video),'bgm':str(bgm),'sfx':str(sfx),
        'source_audio':str(media/'source-audio.wav')},'voice_bank':str(bank_path),'voices':voices,'units':units,
        'tts_workers':3,'output_dir':str(folder/'dub-v1'),'warnings':manifest['warnings']+
        ['Speaker and emotion annotations are screenplay-supported candidates; native listening review pending.']}
    plan_path=folder/'dub-plan-v1.json'
    if plan_path.exists():
        saved=read_json(plan_path)
        # Clone references are decisions persisted at first preparation, not a
        # live projection of the bank. A successful clone must not change input.
        candidate={**plan,'voices':saved['voices']}
        if fingerprint(candidate)!=fingerprint(saved):
            raise ValueError('Reviewed episode inputs changed; existing plan preserved, inspect before resuming')
        print('Existing plan preserved',episode)
        return
    for name in voices:
        if name in bank['voices']:continue
        if any(u['speaker']=='unknown' and u['production_voice']==name for u in units):
            raise ValueError('Unknown reader: identify and assign a reusable voice before any new clone; no per-episode automatic narrator cloning')
        candidates=sorted([u for u in units if u['production_voice']==name],key=lambda u:u['end']-u['start'],reverse=True)
        segments=[];duration=0
        for u in candidates:
            start=max(0,u['start']);end=u['end']
            segments.append([start,end]);duration+=end-start
            if duration>=14:break
        if duration<10:raise ValueError(f'{name} has <10 seconds reference in this episode; collect more actual source voice first')
        voices[name]={'segments_seconds':sorted(segments)}
    save_json(plan_path,plan);print('Plan ready',episode,'utterances',len(units),'voices',list(voices))


if __name__=='__main__':main()
