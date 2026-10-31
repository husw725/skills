"""Prepare first-episode role reference candidates, without uploads or clone calls."""
import argparse
from pathlib import Path
import re
import sys
from dub_episode import digest, probe, run
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
import prepare_monte_editorial_queue as editorial

ROOT = Path('output/review-project-100/voice-preparation-20261031')


def build(ffmpeg):
    source_path=Path('output/review-project-100/subtitles/dialogue.en.json')
    source=read_json(source_path)['segments']
    if len(source)!=854:raise ValueError('Original source collection changed')
    assets=read_json('output/review-project-100/netdisk-source-preparation/progress.private.json')['assets']
    inputs={str(source_path):digest(source_path)};turns=[];first_roles=set()
    for episode in (1,2,3):
        folder=Path('output/review-project-100/episode-01/editorial-candidate-20261030') if episode==1 else Path(f'output/review-project-100/episode-{episode:02d}/editorial-candidate-20261031')
        result=editorial.validate_artifacts(episode,folder)
        inputs[str(folder/'editorial-result.private.json')]=digest(folder/'editorial-result.private.json')
        rows=[r for r in source if int(r['episode'])==episode]
        saved_context=read_json(folder/'source-input.private.json')
        if (saved_context['physical_inputs_sha256'][str(source_path)]!=inputs[str(source_path)]
          or [{k:r[k] for k in ('id','episode','start','end','text')} for r in rows]!=saved_context['timed_source']):
            raise ValueError('Original subtitle text or windows differ from the reviewed snapshot')
        for name in ('source-input.private.json','source-fingerprint.private.json','pt-BR-candidate.srt'):
            inputs[str(folder/name)]=digest(folder/name)
        cue_map={c['id']:c for c in result['candidate']['cues']}
        if set(cue_map)!={r['id'] for r in rows}:raise ValueError('Missing source cue evidence')
        if episode==1:first_roles={c['script_role'] for c in cue_map.values()}
        choices=[a for a in assets.values() if a['kind']=='dialog' and a['episode']==episode]
        if len(choices)!=1:raise ValueError('Unresolved dialogue track version')
        track=choices[0];path=Path(track['path'])
        if digest(path)!=track['sha256']:raise ValueError('Original dialogue track changed')
        inputs[str(path)]=track['sha256']
        grouped=[]
        for row in rows:
            cue=cue_map[row['id']];role=cue['script_role']
            if grouped and grouped[-1]['role']==role and row['start']-grouped[-1]['end']<=1.0:
                group=grouped[-1];group['end']=max(group['end'],row['end']);group['cue_ids'].append(row['id']);group['text']+=' '+row['text']
            else:grouped.append({'role':role,'episode':episode,'start':row['start'],'end':row['end'],
                'cue_ids':[row['id']],'text':row['text'],'source':str(path),'source_sha256':track['sha256']})
        for index,group in enumerate(grouped):
            before=grouped[index-1]['end'] if index else 0
            after=grouped[index+1]['start'] if index+1<len(grouped) else float(probe(path,ffmpeg)['format']['duration'])
            group['extract_start']=max(0,group['start']-.2,before+.05 if index else 0)
            group['extract_end']=min(group['end']+.2,after-.05)
            if group['extract_end']>group['extract_start']:turns.append(group)
    if ('unknown' in first_roles or len(first_roles)!=5
      or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,60}',role) for role in first_roles)):
        raise ValueError('First episode role scope needs review')
    references={}
    for role in sorted(first_roles):
        eligible=[t for t in turns if t['role']==role and len(re.findall(r"[A-Za-z]+",t['text']))>=4
            and 1.2<=t['end']-t['start']<=18]
        eligible.sort(key=lambda t:('!' in t['text'],t['episode'],t['start']))
        selected=[];seconds=0
        for turn in eligible:
            selected.append(turn);seconds+=turn['extract_end']-turn['extract_start']
            if seconds>=13:break
        if not 10<=seconds<=45:raise ValueError('Insufficient clean-length role reference candidate')
        references[role]={'segments':selected,'estimated_seconds':seconds,
            'source_role_attribution':'screenplay_and_timed_dialogue_candidate',
            'source_speaker_audio_verified':False,'track_purity_verified':False,
            'sampled_audio_lag_not_automatically_applied':True}
    return {'project_id':100,'episode':1,'inputs_sha256':inputs,'roles':references,
        'clone_calls':0,'tts_calls':0,'ready_for_clone':False,
        'next_review':'check reference transcript, speaker consistency and purity before one-time voice-bank creation'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--ffmpeg',required=True,type=Path)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows media execution only')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'references.lock',timeout=0):
        plan=build(args.ffmpeg);fp=fingerprint(plan);marker=ROOT/'input-fingerprint.private.json'
        if marker.exists() and read_json(marker)['fingerprint']!=fp:raise ValueError('Reference source changed; preserve old version')
        save_json(marker,{'fingerprint':fp});save_json(ROOT/'reference-proposal.private.json',plan)
        state={'stage':'preparing_reference_candidates','roles':{},'clone_calls':0,'tts_calls':0}
        for role,reference in plan['roles'].items():
            folder=ROOT/role;folder.mkdir(exist_ok=True);target=folder/'reference.wav';receipt=folder/'receipt.private.json'
            if receipt.exists() and not target.exists():raise ValueError('Completed reference WAV is missing; preserve receipt for reconciliation')
            if target.exists():
                saved=read_json(receipt)
                if (saved['input_fingerprint']!=fp or saved['role']!=role or saved['sha256']!=digest(target)
                  or not 10<=saved['seconds']<=45 or target.stat().st_size>16*1024*1024):
                    raise ValueError('Reference cache differs')
            else:
                parts=[]
                for index,segment in enumerate(reference['segments']):
                    part=folder/f'part-{index:02d}.wav'
                    run([args.ffmpeg,'-nostdin','-v','error','-y','-ss',str(segment['extract_start']),
                        '-i',segment['source'],'-t',str(segment['extract_end']-segment['extract_start']),
                        '-ar','44100','-ac','1','-c:a','pcm_s16le',part]);parts.append(part)
                command=[args.ffmpeg,'-nostdin','-v','error','-y']
                for part in parts:command+=['-i',str(part)]
                graph=''.join(f'[{i}:a]' for i in range(len(parts)))+f'concat=n={len(parts)}:v=0:a=1[out]'
                run(command+['-filter_complex',graph,'-map','[out]','-c:a','pcm_s16le',target])
                seconds=float(probe(target,args.ffmpeg)['format']['duration'])
                if not 10<=seconds<=45 or target.stat().st_size>16*1024*1024:raise ValueError('Reference media outside bounds')
                save_json(receipt,{'input_fingerprint':fp,'sha256':digest(target),'seconds':seconds,'role':role})
            state['roles'][role]={'path':str(target),'sha256':digest(target)}
            save_json(ROOT/'progress.private.json',state)
        state['stage']='reference_candidates_ready_quality_review_pending';save_json(ROOT/'progress.private.json',state)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        ROOT.mkdir(parents=True,exist_ok=True)
        save_json(ROOT/'progress.private.json',{'stage':'reference_preparation_needs_review','error_type':type(exc).__name__,'clone_calls':0,'tts_calls':0})
        raise
