"""Render source-bound comment repair candidates from existing fitted groups. No APIs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import numpy as np
from dub_episode import RATE, digest, probe, read_audio, run, write_audio
from process_lock import process_lock
from translate import read_json, save_json


def binding(record):
    p = Path(record['path'])
    if digest(p) != record['sha256']:raise ValueError('Bound input changed')
    return p


def snapshot(record):
    data = Path(record['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != record['sha256']:raise ValueError('Bound JSON changed')
    return json.loads(data.decode('utf-8-sig'))


def assemble(items, sample_count, loader):
    out = np.zeros(sample_count, dtype=np.float32)
    for item in items:
        start = item['start']
        if type(start) not in (int, float) or not math.isfinite(start) or start < 0:raise ValueError('Invalid group placement')
        gain = item.get('gain', 1.0)
        if type(gain) not in (int, float) or not math.isfinite(gain) or gain < 0:raise ValueError('Invalid dialogue gain')
        audio = np.asarray(loader(item), dtype=np.float32)
        if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():raise ValueError('Invalid fitted audio')
        first = round(start * RATE);last = first + len(audio)
        if last > sample_count:raise ValueError('Fitted speech exceeds picture')
        out[first:last] += audio * gain
    return out


def envelope(count, events, rate=RATE):
    out = np.ones(count, dtype=np.float32)
    for event in events:
        vals = [event[k] for k in ('start', 'end', 'gain', 'attack', 'release')]
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in vals):raise ValueError('Finite duck values required')
        start,end,gain,attack,release = vals
        if not 0 <= start < end <= count/rate or not 0 <= gain <= 1 or min(attack,release) < 0:raise ValueError('Duck event outside timeline')
        left=max(0,math.floor((start-attack)*rate));right=min(count,math.ceil((end+release)*rate))
        t=np.arange(left,right,dtype=np.float64)/rate
        candidate=np.full(len(t),gain,dtype=np.float64)
        if attack:
            mask=t<start;candidate[mask]=1-(1-gain)*np.clip((t[mask]-(start-attack))/attack,0,1)
        if release:
            mask=t>=end;candidate[mask]=gain+(1-gain)*np.clip((t[mask]-end)/release,0,1)
        # Overlapping events choose the lower gain; they never multiply repeatedly.
        out[left:right]=np.minimum(out[left:right],candidate)
    return out


def stereo(path, ffmpeg):
    r=subprocess.run([str(ffmpeg),'-nostdin','-v','error','-i',str(path),'-ar',str(RATE),'-ac','2','-f','f32le','-'],capture_output=True)
    if r.returncode or len(r.stdout)%8:raise ValueError('Background decode failed')
    a=np.frombuffer(r.stdout,dtype='<f4').reshape(-1,2).copy()
    if not len(a) or not np.isfinite(a).all():raise ValueError('Background empty/nonfinite')
    return a


def copy_subtitle(source, target, expected_sha256):
    shutil.copyfile(source, target)
    if digest(target) != expected_sha256:raise ValueError('Copied subtitle differs from approved bytes')


def render(row, output, ffmpeg):
    records={k:row[k] for k in ('current_report','speech_plan','fit_report','generation','picture','dialogue','background','subtitle_before','subtitle_after')}
    files={k:binding(v) for k,v in records.items()};base=snapshot(row['current_report']);plan=snapshot(row['speech_plan']);fit=snapshot(row['fit_report']);gen=snapshot(row['generation'])
    if (base['episode']!=row['episode'] or base['output_sha256']!=row['picture']['sha256']
        or base['subtitle_sha256']!=row['subtitle_before']['sha256'] or base['aligned_background_sha256']!=row['background']['sha256']
        or base['inputs']['dialogue']['sha256']!=row['dialogue']['sha256']
        or fit['plan_sha256']!=row['speech_plan']['sha256'] or fit['generation_sha256']!=row['generation']['sha256']
        or gen['plan_sha256']!=row['speech_plan']['sha256'] or fit['blocked']
        or plan.get('project_id')!=100 or plan.get('episode')!=row['episode']
        or [x['id'] for x in plan['groups']]!=[x['id'] for x in fit['groups']]
        or [x['group_id'] for x in gen['groups']]!=[x['id'] for x in plan['groups']]):raise ValueError('Current production chain differs')
    attempt=output/f'attempt-{uuid.uuid4().hex}';attempt.mkdir(parents=True)
    original=read_audio(files['dialogue'],ffmpeg)
    observed_lengths={}
    def load(item):
        if digest(item['path'])!=item['sha256']:raise ValueError('Fitted group changed')
        audio=read_audio(item['path'],ffmpeg);observed_lengths[(item['path'],item['sha256'])]=len(audio);return audio
    prior=assemble(fit['groups'],len(original),load)
    reconstructed=attempt/'baseline-dialogue-check.wav';write_audio(reconstructed,prior)
    if digest(reconstructed)!=row['dialogue']['sha256']:raise ValueError('Fit groups do not reconstruct current paid dialogue')
    old_sizes={g['id']:observed_lengths[(g['path'],g['sha256'])] for g in fit['groups']}
    replacements=row.get('replacements',[]);byid={x['id']:dict(x) for x in fit['groups']};seen=set()
    for patch in replacements:
        key=patch['group_id']
        if key not in byid or key in seen:raise ValueError('Unknown/duplicate replacement group')
        seen.add(key);audio=binding(patch['audio']);receipt=snapshot(patch['receipt'])
        if receipt.get('placed_audio_sha256')!=patch['audio']['sha256'] or receipt.get('group_id')!=key:
            raise ValueError('Replacement receipt differs')
        # Route/task/raw/placed evidence is independently approved with this frozen scope.
        byid[key].update(path=str(audio),sha256=patch['audio']['sha256'],start=patch['start'])
    for key,edit in row.get('placement_overrides',{}).items():
        if key not in byid:raise ValueError('Unknown placement group')
        byid[key]['start']=edit
    for key,gain in row.get('dialogue_gains',{}).items():
        if key not in byid:raise ValueError('Unknown gain group')
        byid[key]['gain']=gain
    adopted=[byid[x['id']] for x in fit['groups']]
    # Preserve original declared chronological ordering; a new overlap needs a separate plan.
    for first,second in zip(adopted,adopted[1:]):
        if first['start']>second['start']:raise ValueError('Reordered dialogue groups')
    dialogue=assemble(adopted,len(original),load)
    for item in adopted:
        end=item['start']+observed_lengths[(item['path'],item['sha256'])]/RATE
        if end>item['end_limit']+.005:raise ValueError('Replacement exceeds original safe speech boundary')
    for i,(first,second) in enumerate(zip(adopted,adopted[1:])):
        original_first,original_second=fit['groups'][i:i+2]
        allowed=max(0,original_first['start']+old_sizes[original_first['id']]/RATE-original_second['start'])
        overlap=max(0,first['start']+observed_lengths[(first['path'],first['sha256'])]/RATE-second['start'])
        if overlap>allowed+.005:raise ValueError('New speech overlaps neighboring group')
    if float(np.max(np.abs(dialogue)))>=1:raise ValueError('New dialogue would clip before final mixing')
    dry=attempt/'dialogue-pt-BR.wav';write_audio(dry,dialogue)
    duration=float(probe(files['picture'],ffmpeg)['format']['duration'])
    if abs(len(original)/RATE-duration)>.05:raise ValueError('Dialogue and picture axes differ')
    bg=stereo(files['background'],ffmpeg);pad=max(0,len(original)-len(bg))
    if pad>math.ceil(.05*RATE):raise ValueError('Background too short; no implicit long pad')
    if pad:bg=np.pad(bg,((0,pad),(0,0)))
    bg=bg[:len(original)];gain=envelope(len(original),row.get('ducking',[]));bg*=gain[:,None]
    import soundfile as sf
    bed=attempt/'background-adjusted.wav';sf.write(str(bed),bg,RATE,subtype='FLOAT')
    mix=attempt/'mix-pt-BR.wav'
    run([ffmpeg,'-nostdin','-v','error','-i',dry,'-i',bed,'-filter_complex',
         f'[0:a]apad,atrim=duration={duration}[d];[d][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
         '-map','[out]','-ar',str(RATE),'-ac','2','-c:a','pcm_s16le',mix])
    final=attempt/f'The_Count_of_Monte_Cristo_EP{row["episode"]:02d}_pt-BR_comment-revision.mp4'
    run([ffmpeg,'-nostdin','-v','error','-i',files['picture'],'-i',mix,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',final])
    run([ffmpeg,'-nostdin','-v','error','-xerror','-i',final,'-f','null','-'])
    hashes=[run([ffmpeg,'-nostdin','-v','error','-i',p,'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip() for p in (files['picture'],final)]
    if hashes[0]!=hashes[1]:raise ValueError('Picture payload changed')
    if abs(float(probe(final,ffmpeg)['format']['duration'])-duration)>.05:raise ValueError('Output duration differs')
    subtitle=attempt/f'The Count of Monte Cristo EP{row["episode"]:02d} V{row["subtitle_version"]}.srt';copy_subtitle(files['subtitle_after'],subtitle,row['subtitle_after']['sha256'])
    for record in records.values():binding(record)
    for item in adopted:load(item)  # verify actual adopted input hashes again
    report={'episode':row['episode'],'stage':'comment_repair_candidate','inputs':row,'output':str(final),'output_sha256':digest(final),
            'subtitle':str(subtitle),'subtitle_sha256':digest(subtitle),'picture_payload_identical':True,'full_decode_passed':True,
            'dialogue_reconstructed_from_existing_groups':True,'new_tts_in_renderer':0,'new_clones':0,'replacement_groups':sorted(seen),
            'background_tail_pad_samples':pad,'ducking':row.get('ducking',[]),'dialogue':str(dry),'dialogue_sha256':digest(dry),
            'background':str(bed),'background_sha256':digest(bed),'adopted_groups':adopted,'native_listening_passed':False,'mix_listening_passed':False,'published':False}
    rp=attempt/'render-report.private.json';save_json(rp,report);return {'report':str(rp),'report_sha256':digest(rp),'status':'candidate_rendered'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--ffmpeg',type=Path,required=True);a=p.parse_args()
    if sys.platform!='win32':raise ValueError('Business media runs on Windows')
    data=a.manifest.read_bytes();m=json.loads(data.decode('utf-8-sig'));sig=hashlib.sha256(data).hexdigest();approval=read_json(a.approval)
    if approval.get('manifest_sha256')!=sig or approval.get('technical_repair_render_approved') is not True:raise ValueError('Source-bound repair review required')
    eps=[r['episode'] for r in m['episodes']]
    if m.get('film')!='The Count of Monte Cristo' or not eps or len(eps)!=len(set(eps)):raise ValueError('Wrong/duplicate episode scope')
    a.output.mkdir(parents=True,exist_ok=True)
    with process_lock(a.output/'render.lock',timeout=0):
        pp=a.output/'progress.private.json';state=read_json(pp) if pp.exists() else {'manifest_sha256':sig,'episodes':{}}
        if state['manifest_sha256']!=sig:raise ValueError('Keep prior scope; use a new candidate directory')
        for row in m['episodes']:
            key=str(row['episode'])
            if key in state['episodes']:
                old=state['episodes'][key];r=snapshot({'path':old['report'],'sha256':old['report_sha256']});binding({'path':r['output'],'sha256':r['output_sha256']});binding({'path':r['subtitle'],'sha256':r['subtitle_sha256']});continue
            state['episodes'][key]=render(row,a.output/f'episode-{row["episode"]:02d}',a.ffmpeg);save_json(pp,state)
            print('COMMENT_REPAIR_RENDERED',row['episode'],flush=True)


if __name__=='__main__':main()
