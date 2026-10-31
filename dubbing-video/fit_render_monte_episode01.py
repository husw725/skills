"""Fit existing paid speech without new synthesis, then copy the original picture."""
import argparse
import math
from pathlib import Path
import sys
import numpy as np
from dub_episode import RATE, digest, probe, read_audio, run, trim_edges, write_audio
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
from generate_monte_episode01 import ROOT, build_plan
from review_drama_source_asr import MANIFEST_FINGERPRINT


def media_inputs():
    manifest=read_json('output/four-dramas-20261030/intake-manifest.private.json')
    if fingerprint(manifest)!=MANIFEST_FINGERPRINT:raise ValueError('Pinned source batch changed')
    items=[x for x in manifest['items'] if x['project_id']==100 and x['kind']=='video'
        and x['episode']==1 and x['variant']=='nosub_label_not_visual_verification']
    if len(items)!=1:raise ValueError('First episode source cut ambiguous')
    item=items[0]
    inspected=read_json(Path('output/review-project-100/source-preparation')/f'asset-{item["asset_id"]}-v{item["version"]}.private.json')
    if any(inspected['source_asset'][k]!=item[k] for k in ('project_id','asset_id','version')):
        raise ValueError('Picture inspection belongs to another asset')
    video=Path(inspected['source_asset']['path'])
    if digest(video)!=inspected['source_sha256']:raise ValueError('Original picture changed')
    assets=read_json('output/review-project-100/netdisk-source-preparation/progress.private.json')['assets']
    tracks=[a for a in assets.values() if a['kind']=='sfx' and a['episode']==1]
    if len(tracks)!=1:raise ValueError('Background source cut ambiguous')
    background=Path(tracks[0]['path'])
    if digest(background)!=tracks[0]['sha256']:raise ValueError('Original background changed')
    return video,background


def fitted(plan,ffmpeg,media=None):
    generated=read_json(ROOT/'generation-result.private.json')
    plan_sha=digest(ROOT/'speech-plan.private.json')
    if generated['plan_sha256']!=plan_sha or [g['group_id'] for g in generated['groups']]!=[g['id'] for g in plan['groups']]:
        raise ValueError('Generated speech coverage differs')
    video,background=media_inputs() if media is None else media;duration=float(probe(video,ffmpeg)['format']['duration'])
    report={'plan_sha256':plan_sha,'generation_sha256':digest(ROOT/'generation-result.private.json'),
        'media_sha256':{str(video):digest(video),str(background):digest(background)},'groups':[],
        'blocked':[],'new_tts':0,'new_clones':0,'native_listening_passed':False}
    for index,(group,raw) in enumerate(zip(plan['groups'],generated['groups'])):
        path=Path(raw['raw_path'])
        if digest(path)!=raw['raw_sha256'] or raw['key']!=group['cache_key']:raise ValueError('Paid raw audio changed')
        audio,left,right=trim_edges(read_audio(path,ffmpeg))
        raw_duration=len(audio)/RATE
        next_start=plan['groups'][index+1]['start'] if index+1<len(plan['groups']) else duration+.08
        end_limit=min(group['end']+.8,next_start-.08,duration)
        available=end_limit-group['start']
        tempo=max(1.0,raw_duration/available) if available>0 else math.inf
        if available<=0 or tempo>1.2+1e-8:
            report['blocked'].append({'id':group['id'],'raw_seconds':raw_duration,'available_seconds':available,
                'reason':'Existing speech exceeds timing limit; no new paid retry or word truncation'})
            continue
        folder=ROOT/'fitted'/group['id'];folder.mkdir(parents=True,exist_ok=True)
        binding={'raw_sha256':raw['raw_sha256'],'plan_sha256':plan_sha,'start':group['start'],
            'end_limit':end_limit,'post_atempo':tempo}
        marker=folder/'input.private.json';target=folder/'fitted.wav'
        if marker.exists() and read_json(marker)!=binding:raise ValueError('Existing fitted source changed')
        save_json(marker,binding)
        receipt=folder/'receipt.private.json'
        if receipt.exists():
            item=read_json(receipt)
            if (item['input_fingerprint']!=fingerprint(binding) or digest(target)!=item['sha256']
                or item['start']!=group['start'] or item['end_limit']!=end_limit
                or abs(float(probe(target,ffmpeg)['format']['duration'])-item['seconds'])>1e-6
                or item['seconds']>available+.02):
                raise ValueError('Existing fitted audio changed')
        else:
            if target.exists():raise ValueError('Orphan fitted audio; preserve for reconciliation')
            trimmed=folder/'trimmed.wav';write_audio(trimmed,audio)
            run([ffmpeg,'-nostdin','-v','error','-y','-i',trimmed,'-af',f'atempo={tempo:.12f}',
                '-ar',str(RATE),'-ac','1','-c:a','pcm_s16le',target])
            actual=float(probe(target,ffmpeg)['format']['duration'])
            if actual>available+.02:
                report['blocked'].append({'id':group['id'],'reason':'Post-filter duration exceeds available window'})
                continue
            item={'id':group['id'],'path':str(target),'sha256':digest(target),'start':group['start'],
                'seconds':actual,'source_display_end':group['end'],'end_limit':end_limit,
                'synthesis_speed':group['request']['speed'],'post_atempo':tempo,
                'nominal_combined_rate':group['request']['speed']*tempo,
                ('edge_trim_samples' if media is None else 'edge_trim_seconds'):[left,right],'input_fingerprint':fingerprint(binding)}
            save_json(receipt,item)
        report['groups'].append(item)
    save_json(ROOT/'fit-report.private.json',report)
    save_json(ROOT/'progress.private.json',{'stage':'speech_fit_blocked' if report['blocked'] else 'speech_fitted_render_pending',
        'fitted':len(report['groups']),'blocked':report['blocked'],'new_tts':0,'new_clones':0})
    return report


def render(plan,fit,ffmpeg,media=None,filename=None):
    if fit['blocked'] or len(fit['groups'])!=len(plan['groups']):raise ValueError('Do not render unresolved timing')
    video,background=media_inputs() if media is None else media
    if fit['media_sha256']!={str(video):digest(video),str(background):digest(background)}:
        raise ValueError('Fitted source media changed')
    duration=float(probe(video,ffmpeg)['format']['duration']);samples=np.zeros(math.ceil(duration*RATE),np.float32)
    for item in fit['groups']:
        path=Path(item['path'])
        if digest(path)!=item['sha256']:raise ValueError('Fitted waveform changed')
        audio=read_audio(path,ffmpeg);start=round(item['start']*RATE)
        if start+len(audio)>len(samples):raise ValueError('Speech exceeds picture duration')
        samples[start:start+len(audio)]+=audio
    dialogue=ROOT/'dialogue-pt-BR.wav';write_audio(dialogue,samples)
    mix=ROOT/'mix-pt-BR.wav'
    run([ffmpeg,'-nostdin','-v','error','-y','-i',dialogue,'-i',background,
        '-filter_complex',f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[d][b]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
        '-map','[out]','-ar',str(RATE),'-ac','2','-c:a','pcm_s16le',mix])
    final=ROOT/(filename or 'The_Count_of_Monte_Cristo_EP01_pt-BR.mp4')
    run([ffmpeg,'-nostdin','-v','error','-y','-i',video,'-i',mix,'-map','0:v:0','-map','1:a:0',
        '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',final])
    run([ffmpeg,'-nostdin','-v','error','-xerror','-i',final,'-f','null','-'])
    hashes=[run([ffmpeg,'-nostdin','-v','error','-i',p,'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip() for p in (video,final)]
    if hashes[0]!=hashes[1]:raise ValueError('Picture payload changed')
    report={'plan_sha256':digest(ROOT/'speech-plan.private.json'),'fit_report_sha256':digest(ROOT/'fit-report.private.json'),
        'output':str(final),'output_sha256':digest(final),'picture_payload_identical':True,
        'original_dialogue_track_included':False,'background_source':str(background),'background_sha256':digest(background),
        'subtitle':str(ROOT/'pt-BR-production-candidate.srt'),'subtitle_sha256':digest(ROOT/'pt-BR-production-candidate.srt'),
        'native_listening_passed':False,'full_background_timeline_verified':False,'new_tts':0,'new_clones':0}
    save_json(ROOT/'render-report.private.json',report)
    save_json(ROOT/'progress.private.json',{'stage':'episode_candidate_rendered_media_review_pending',
        'output':str(final),'native_listening_passed':False})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ffmpeg',required=True,type=Path);args=p.parse_args()
    if sys.platform!='win32':raise ValueError('Windows media processing only')
    with process_lock(ROOT/'production.lock',timeout=0):
        plan=read_json(ROOT/'speech-plan.private.json')
        if plan!=build_plan():raise ValueError('Current source or voice bank changed')
        fit=fitted(plan,args.ffmpeg)
        if not fit['blocked']:render(plan,fit,args.ffmpeg)


if __name__=='__main__':main()
