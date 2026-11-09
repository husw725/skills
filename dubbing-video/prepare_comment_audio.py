"""Prepare finite comment audio patches from paid results; no synthesis or upload."""
import argparse
import math
from pathlib import Path
import sys
import numpy as np
from dub_episode import RATE,digest,read_audio,write_audio,trim_edges,probe,run
from translate import read_json,save_json
from process_lock import process_lock
from generate_comment_repairs import validate,bound
import generate_monte_episode01 as speech


def insert_pause(audio,cut,added):
    audio=np.asarray(audio)
    if audio.ndim!=1 or not len(audio) or not np.isfinite(audio).all():raise ValueError('Finite mono source required')
    if type(cut) is not int or type(added) is not int or not 0<cut<len(audio) or added<=0:raise ValueError('Invalid finite pause')
    # Only split a measured quiet interval; retain every source sample and word.
    zone=audio[max(0,cut-round(.01*RATE)):min(len(audio),cut+round(.01*RATE))]
    if np.sqrt(np.mean(np.square(zone.astype(np.float64))))>10**(-50/20):raise ValueError('Pause cut intersects audible signal')
    return np.concatenate([audio[:cut],np.zeros(added,dtype=audio.dtype),audio[cut:]])



def remove_quiet_interval(audio,first,last):
    audio=np.asarray(audio)
    if audio.ndim!=1 or not len(audio) or not np.isfinite(audio).all():raise ValueError('Finite mono source required')
    if type(first) is not int or type(last) is not int or not 0<first<last<len(audio):raise ValueError('Invalid quiet interval')
    zone=audio[first:last].astype(np.float64)
    # An average alone can hide a brief spoken onset or breath inside a long gap.
    if np.max(np.abs(zone))>10**(-45/20):raise ValueError('Interval contains audible signal')
    return np.concatenate([audio[:first],audio[last:]])


def fit_repairs(planpath,ffmpeg):
    plan=validate(planpath);folder=planpath.parent;generation=read_json(folder/'generation-result.private.json')
    if generation['plan_sha256']!=digest(planpath) or [x['group_id'] for x in generation['groups']]!=[x['id'] for x in plan['groups']]:raise ValueError('Paid result differs from reviewed plan')
    baseline=bound(plan['baseline_packet']);original={x['id']:x for x in baseline['fit']['groups']}
    if baseline['plan_path']!=plan['baseline_plan']['path'] or baseline['parent_report']['plan_sha256']!=plan['baseline_plan']['sha256']:raise ValueError('Fit baseline differs')
    out=[];blocked=[]
    for g,raw in zip(plan['groups'],generation['groups']):
        if raw['key']!=g['cache_key'] or digest(raw['raw_path'])!=raw['raw_sha256']:raise ValueError('Paid waveform identity changed')
        cache=Path('output/review-project-100/paid-speech-cache')
        req,task,receipt=speech.read_cache(cache/g['cache_key'],g['cache_key'],g['request'])
        if (receipt is None or raw['task_id']!=task or raw['raw_sha256']!=receipt['sha256']
            or raw['request_fingerprint']!=speech.fingerprint(req)
            or Path(raw['raw_path'])!=speech.recovery_folder(cache/g['cache_key'],g['cache_key'],g['request'])/'raw.wav'):
            raise ValueError('Waveform is not the successful authoritative paid result')
        old=original[g['source_group_id']]
        if digest(old['path'])!=old['sha256']:raise ValueError('Original placement changed')
        oldaudio=read_audio(old['path'],ffmpeg)
        # Never infer a sparse repair plan\'s next selected group is the actual neighbour.
        end=max(old['end_limit'],old['start']+len(oldaudio)/RATE)
        index=baseline['fit']['groups'].index(old)
        if index+1<len(baseline['fit']['groups']):
            next_start=baseline['fit']['groups'][index+1]['start']
            old_overlap=max(0,old['start']+len(oldaudio)/RATE-next_start)
            end=min(end,next_start+old_overlap)
        audio,left,right=trim_edges(read_audio(raw['raw_path'],ffmpeg));available=end-old['start'];headroom=min(.015,max(0,available)*.05);target_seconds=available-headroom
        tempo=max(1.0,len(audio)/RATE/target_seconds) if target_seconds>0 else math.inf
        if tempo>1.2+1e-8:
            blocked.append(dict(group_id=g['source_group_id'],reason='Exceeds preserved neighbour boundary without natural fit; no automatic paid retry',post_atempo_required=tempo));continue
        dest=folder/'fitted-v2'/g['id'];dest.mkdir(parents=True,exist_ok=True);target=dest/'fitted.wav';rp=dest/'receipt.private.json'
        inputs=dict(group_id=g['source_group_id'],repair_group_id=g['id'],raw_audio_sha256=raw['raw_sha256'],raw_task_id=raw['task_id'],paid_request_key=raw['key'],generation_sha256=digest(folder/'generation-result.private.json'),plan_sha256=digest(planpath),baseline_packet_sha256=plan['baseline_packet']['sha256'],start=old['start'],end_limit=end,edge_trim_seconds=[left,right],synthesis_speed=g['request']['speed'],post_atempo=tempo,nominal_combined_rate=g['request']['speed']*tempo,encoding_headroom_seconds=headroom)
        if rp.exists():
            receipt=read_json(rp)
            if receipt['inputs']!=inputs or digest(target)!=receipt['placed_audio_sha256']:raise ValueError('Existing repair audio changed')
        else:
            if target.exists():raise ValueError('Orphan repair audio: preserve for reconciliation')
            trimmed=dest/'trimmed.wav';write_audio(trimmed,audio)
            run([ffmpeg,'-nostdin','-v','error','-i',trimmed,'-af',f'atempo={tempo:.12f}','-ar',str(RATE),'-ac','1','-c:a','pcm_s16le',target])
            seconds=float(probe(target,ffmpeg)['format']['duration'])
            if seconds>available+.005:raise ValueError('Filtered repair exceeds exact speech boundary')
            receipt=dict(group_id=g['source_group_id'],placed_audio_sha256=digest(target),inputs=inputs,seconds=seconds,native_listening_passed=False,voice_listening_passed=False)
            save_json(rp,receipt)
        out.append(dict(group_id=g['source_group_id'],audio=dict(path=str(target),sha256=digest(target)),receipt=dict(path=str(rp),sha256=digest(rp)),start=old['start']))
    report=dict(plan_sha256=digest(planpath),generation_sha256=digest(folder/'generation-result.private.json'),replacements=out,blocked=blocked,new_tts=0,new_clones=0,native_listening_passed=False)
    save_json(folder/'patches.private.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--ffmpeg',type=Path,required=True);a=p.parse_args()
    if sys.platform!='win32':raise ValueError('Business audio runs on Windows')
    with process_lock(a.plan.parent/'production.lock',timeout=0):r=fit_repairs(a.plan,a.ffmpeg)
    print('COMMENT_AUDIO_PATCHES',len(r['replacements']),'BLOCKED',len(r['blocked']))


if __name__=='__main__':main()
