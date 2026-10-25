"""Source-bound, finite whole-context candidate. No new cloning or paid retries."""
import argparse
import copy
import itertools
import math
from pathlib import Path
import re
import sys
import time
from collections import Counter

from translate import read_json, save_json, fingerprint
from dub_episode import digest, read_audio, RATE
from process_lock import process_lock
from cartesia_pilot import bind
from clone_feedback_pilot import expected_request
from clone_feedback_v2 import completed
from repair_episode_feedback import generate
from rerun_carmilla_season import paid_cache_roots, fit_speech
from mflix_client import Mflix
import systematic_ptbr_review as baseline

PARENT_ROOT=Path('output/contextual-ptbr-candidate-20261024')
ROOT=PARENT_ROOT
TIMING_REVISION=False
MAX_NEW_REQUESTS=33
BANK=Path('output/drama-01/voice-bank.json')
SCENES=((5,93.,tuple(f'e05-group-{i:03}' for i in range(24,33))),
        (17,0.,tuple(f'e17-group-{i:03}' for i in range(1,15))),
        (24,0.,tuple(f'e24-group-{i:03}' for i in range(1,15))))
GROUPS=(('e17-group-008','e17-group-009'),('e17-group-011','e17-group-012'),('e24-group-012','e24-group-013'))
CHANGES={'e05-group-025','e05-group-028','e17-group-004','e17-group-009'}
CAPS={'e24-group-002','e24-group-003','e24-group-006','e24-group-011'}
ROLES={'Laura','Carmilla','Father','Irina'}
REPAIR_IDS={'e05-group-031','e17-group-004'}


def configure_timing_revision():
    global ROOT,TIMING_REVISION,MAX_NEW_REQUESTS,CHANGES
    ROOT=Path('output/contextual-ptbr-candidate-20261025-timing-v2')
    TIMING_REVISION=True;MAX_NEW_REQUESTS=2;CHANGES=CHANGES|{'e05-group-031'}


def numeric_request_variants(req):
    """Only JSON numeric spelling may vary; old receipts/markers stay unchanged."""
    choices=[]
    for k in ('speed','vol','pitch'):
        v=req[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
            raise ValueError('Finite numeric synthesis controls required; never coerce bool/string')
        choices.append((int(v),float(v)) if float(v).is_integer() else (v,))
    variants={}
    for values in itertools.product(*choices):
        r=copy.deepcopy(req)
        for k,v in zip(('speed','vol','pitch'),values):r[k]=v
        variants[fingerprint(r)]=r
    return variants


def parent_basis(proposal):
    old=read_json(PARENT_ROOT/'manifest.private.json');approval=read_json(PARENT_ROOT/'editorial-approval.private.json')
    if (fingerprint(old)!='16df4425f0487a88857ae588466095b76b84d287aedd77c461d87bfeb1da072b'
      or approval['manifest_fingerprint']!=fingerprint(old) or digest(approval['report_path'])!=approval['report_sha256']):
        raise ValueError('Exact independently approved parent required')
    for p,sha in old['inputs'].items():
        if digest(p)!=sha:raise ValueError('Parent source changed')
    prior=read_json(PARENT_ROOT/'editorial-proposal.private.json')
    if set(proposal)!=set(prior) or any(proposal[k]!=v for k,v in prior.items() if k not in ('translation_changes','paid_request_cap')):
        raise ValueError('Only the two measured timing wordings and new-request cap may change')
    for uid,change in prior['translation_changes'].items():
        if uid not in REPAIR_IDS and proposal['translation_changes'][uid]!=change:raise ValueError('Other editorial wording changed')
    replacements={
      'e05-group-031':('Seus olhos… Tá com febre?',{'e05-35':'Seus olhos… Tá com febre?'}),
      'e17-group-004':('Esse sangue tem dois poderes: pode curar maldições ou incinerar seres da noite.',
        {'e17-4':'Esse sangue tem dois poderes:','e17-5':'pode curar maldições','e17-6':'ou incinerar seres da noite.'})}
    for uid,(text,cues) in replacements.items():
        c=proposal['translation_changes'][uid]
        if c['translation']!=text or c['cue_translations']!=cues:raise ValueError('Unapproved timing replacement')
    f=read_json(PARENT_ROOT/'fit-report.private.json');generated=read_json(PARENT_ROOT/'generation-result.private.json')['results']
    if (f['ready'] or {r['unit_id'] for r in f['blocked']}!=REPAIR_IDS|{'e24-group-008'}
      or f['manifest_sha256']!=digest(PARENT_ROOT/'manifest.private.json')
      or f['generation_sha256']!=digest(PARENT_ROOT/'generation-result.private.json')):
        raise ValueError('Measured exact parent timing blockers required; not a paid retry loop')
    groups={u['id']:u for s in old['scenes'] for u in s['groups']}
    if len(generated)!=33:raise ValueError('Parent finite generation must be complete')
    preferred={}
    for uid,u in groups.items():
        if u['request'] is None:continue
        key=fingerprint(u['request']);r=generated[key]
        if r['request']!=u['request'] or digest(r['path'])!=r['sha256']:raise ValueError('Parent recording changed')
        _,receipt=completed(Path(r['path']).parent,u['request'])
        if receipt['task_id']!=r['task_id']:raise ValueError('Parent task changed')
        if uid not in REPAIR_IDS|{'e24-group-008'}:preferred[key]=r
    s=next(s for s in old['scenes'] if s['episode']==24)
    original=next(u for u in s['source_report']['utterances'] if u['id']=='e24-group-008')
    group=groups['e24-group-008']
    if (original['source_speaker']!='Father' or original['production_voice']!='Father'
      or original['translation']!='Corre!' or original['start']!=group['start']
      or fingerprint(original['request']) not in numeric_request_variants(group['request'])
      or original['atempo_factor']>1.2 or digest(original['fitted_path'])!=original['fitted_sha256']
      or original.get('audio_start',original['start'])+original['fitted_duration_seconds']>group['audio_end_limit']+.000001):
        raise ValueError('Retained Corre must be exact published same-clone, same-word, fitted recording')
    paths=[PARENT_ROOT/f for f in ('manifest.private.json','editorial-proposal.private.json','editorial-approval.private.json',
      'generation-result.private.json','fit-report.private.json')]+[Path(approval['report_path'])]
    return {'parent_input_sha256':{str(p):digest(p) for p in paths},'preferred_parent_audio':preferred,
      'same_clone_original_retained':{'unit_id':'e24-group-008','source':original},
      'parent_paid_request_count':33,'max_additional_requests':2,'total_request_cap':35}


def build_manifest():
    base=read_json(baseline.ROOT/'manifest.private.json');baseline.validate(base)
    proposal=read_json(ROOT/'editorial-proposal.private.json')
    timing=parent_basis(proposal) if TIMING_REVISION else None
    packet=read_json(ROOT/'source-context-packet.private.json');bank=read_json(BANK)['voices']
    if (set(proposal['translation_changes'])!=CHANGES or tuple(tuple(x) for x in proposal['regroups'])!=GROUPS
      or set(proposal['uppercase_performance_units'])!=CAPS or proposal['paid_request_cap']!=MAX_NEW_REQUESTS
      or proposal['timing_policy']!={'max_atempo':1.2,'max_post_gap_seconds':.8,'no_preroll':True,'no_speech_truncation':True,'no_paid_retry':True}):
        raise ValueError('Outside fixed contextual pilot scope')
    if [(c['episode'],c['start'],tuple(c['unit_ids'])) for c in proposal['scene_specs']]!=list(SCENES):
        raise ValueError('Scene boundaries or selected units differ')
    if any(c['end'] is not None for c in proposal['scene_specs']):raise ValueError('Keep complete episode ending')
    for role in ROLES:
        pair=['speech-2.8-hd',bank[role]['voice_id']]
        if pair not in base['whole_season_stats']['voice_configuration_by_role'][role]:
            raise ValueError('Use only previously delivered per-role MiniMax clone')
    inputs={str(p):digest(p) for p in [baseline.ROOT/'manifest.private.json',ROOT/'editorial-proposal.private.json',
      ROOT/'source-context-packet.private.json',BANK]}
    if timing:inputs.update(timing['parent_input_sha256'])
    scenes=[];all_groups=[]
    for spec in proposal['scene_specs']:
        n=spec['episode'];e=copy.deepcopy(next(e for e in base['episodes'] if e['episode']==n));folder=Path(e['folder'])
        plan=read_json(folder/'plan.json');context=read_json(folder/'screenplay-context.json')
        if packet[str(n)]!={'plan':plan,'context':context}:raise ValueError('Reviewed source packet changed')
        if n==24 and context['episodes']['24'].get('storyboard_episode_mapping')!={'actual_episode':24,'html_label':'EP-25','subtitle_times_preserved':True}:
            raise ValueError('EP24 requires the matched EP25 WOUNDED storyboard, not old EP24 script')
        if digest(e['video'])!=e['video_sha256']:raise ValueError('Current episode video changed')
        assets=plan['assets'];report=read_json(folder/'render-report.json')
        for p in [folder/'plan.json',folder/'screenplay-context.json',folder/'reviewed.json',folder/'render-report.json',Path(e['subtitle']),
          Path(assets['video']),Path(assets['bgm']),Path(assets['sfx'])]:inputs[str(p)]=digest(p)
        old={u['id']:u for u in report['utterances']}
        for u in old.values():
            if digest(u['fitted_path'])!=u['fitted_sha256']:raise ValueError('Original fitted audio changed')
            inputs[u['fitted_path']]=u['fitted_sha256']
        selected=[copy.deepcopy(u) for u in plan['units'] if u['id'] in spec['unit_ids']]
        if [u['id'] for u in selected]!=spec['unit_ids']:raise ValueError('Source unit order differs')
        by_id={u['id']:u for u in selected};used=set();groups=[];cue_changes={}
        for u in selected:
            if u['id'] in used:continue
            ids=next((list(g) for g in GROUPS if g[0]==u['id']),[u['id']])
            parts=[by_id[s] for s in ids];used.update(ids)
            if len(parts)>1:
                if (len({p['source_speaker'] for p in parts})!=1 or parts[0]['source_speaker'] in (None,'unknown')
                  or len({p['production_voice'] for p in parts})!=1 or len({p['emotion'] for p in parts})!=1):
                    raise ValueError('Cannot join unknown identities, roles or emotional directions')
                if not 0<=parts[1]['start']-parts[0]['end']<=1.:raise ValueError('Unapproved pause span')
            captions=[]
            for p in parts:
                edit=proposal['translation_changes'].get(p['id'])
                if edit:
                    if set(edit['cue_translations'])!=set(p['cue_ids']):raise ValueError('Subtitle edit scope changed')
                    if ' '.join(edit['cue_translations'][cid] for cid in p['cue_ids'])!=edit['translation']:
                        raise ValueError('Candidate subtitle words and speech differ')
                    captions.append(edit['translation']);cue_changes.update(edit['cue_translations'])
                else:captions.append(p['translation'])
            pause=proposal.get('group_pause_seconds',{}).get(u['id'])
            if len(parts)>1 and pause not in (.25,.45):raise ValueError('Explicit reviewed group pause required')
            text=(f' <#{pause:.2f}#> ' if len(parts)>1 else ' ').join(captions)
            if u['id'] in CAPS:text=text.upper()
            caption=' '.join(captions)
            clean=re.sub(r'<#\d+\.\d+#>',' ',text)
            if re.findall(r'\w+',clean.casefold())!=re.findall(r'\w+',caption.casefold()):raise ValueError('Changed speakable words')
            unknown=any(p.get('source_speaker','unknown')=='unknown' for p in parts)
            if unknown and (len(parts)!=1 or u['id'] in proposal['translation_changes']):raise ValueError('Keep unknown unchanged')
            req=None if unknown else expected_request(u['production_voice'],text,1.,u['emotion'],bank)
            retain_known=TIMING_REVISION and u['id']=='e24-group-008'
            if retain_known:req=None
            if not unknown and u['production_voice'] not in ROLES:raise ValueError('Unapproved voice role')
            groups.append({'id':u['id'],'episode':n,'source_unit_ids':ids,'source_units':parts,
              'start':parts[0]['start'],'end':parts[-1]['end'],'caption':caption,'request':req,
              'production_voice':u['production_voice'],'source_speaker':u['source_speaker'],
              'emotion_direction':u['emotion'],'unknown_retained':unknown})
            if retain_known:groups[-1]['same_clone_original_retained']=True
        if used!=set(spec['unit_ids']):raise ValueError('Source coverage incomplete')
        for i,g in enumerate(groups):
            following=groups[i+1]['start'] if i+1<len(groups) else e['duration_seconds']
            limit=max(g['end'],min(e['duration_seconds'],following-.1,g['end']+.8))
            g['audio_end_limit']=min(following,e['duration_seconds'],limit)
        scenes.append({'id':spec['id'],'episode':n,'start':spec['start'],'end':e['duration_seconds'],
          'base':e,'assets':assets,'source_report':report,'groups':groups,'cue_changes':cue_changes})
        all_groups+=groups
    if len(all_groups)!=34 or sum(g['request'] is not None for g in all_groups)!=(32 if TIMING_REVISION else 33):
        raise ValueError('Expected 37 source units, three joins, one unchanged unknown')
    result={'scenes':scenes,'inputs':inputs,'proposal_sha256':digest(ROOT/'editorial-proposal.private.json'),
      'base_manifest_sha256':digest(baseline.ROOT/'manifest.private.json'),'paid_request_cap':MAX_NEW_REQUESTS,'new_clone_count':0,
      'provider_policy':proposal['provider_policy'],'native_listening_passed':False,
      'screenplay_basis':'Bound reviewed contexts; EP24 uses updated EP25 WOUNDED storyboard mapping; source unknown unchanged',
      'timing_policy':proposal['timing_policy'],'translation_changes':proposal['translation_changes']}
    if timing:
        active={fingerprint(g['request']) for g in all_groups if g['request'] is not None}
        if len(timing['preferred_parent_audio'])!=30 or not set(timing['preferred_parent_audio']).issubset(active):
            raise ValueError('Keep all exact thirty parent recordings')
        result['timing_revision_basis']=timing
    return result


def validate(m,approved=True):
    if m!=build_manifest() or read_json(ROOT/'manifest-fingerprint.json')['fingerprint']!=fingerprint(m):
        raise ValueError('Contextual candidate or source bindings changed')
    for p,sha in m['inputs'].items():
        if digest(p)!=sha:raise ValueError('Pilot physical input changed')
    if approved:
        a=read_json(ROOT/'editorial-approval.private.json')
        if (a['manifest_fingerprint']!=fingerprint(m) or a['native_listening_passed'] is not False
          or a['status']!='independent_editorial_pass' or digest(a['report_path'])!=a['report_sha256']):
            raise ValueError('This exact editorial/context requires independent approval')


def triage():
    base=read_json(baseline.ROOT/'manifest.private.json');rows=[]
    for ep in base['episodes']:
        for u in ep['units']:
            reasons=[];src=u['source_text'].casefold();pt=u['translation'].casefold()
            if re.search(r"\b(?:not|never|no|cannot|can't|don't|won't|nobody|nothing)\b",src) and not re.search(r'\b(?:não|nunca|ninguém|nada|nem|sem|nenhum|nenhuma)\b',pt):
                reasons.append('Source negation without a literal PT negative word: idiomatic equivalence needs contextual review, not an automatic error')
            if len(re.findall(r'\w+',pt))>=12:reasons.append('Long complete thought; inspect register, semantic completeness and rhythm')
            if u['atempo_factor']>=1.15:reasons.append('Existing acceleration >=1.15; inspect clarity and timing, not a proven defect')
            if u['emotion'] in ('fearful','angry') and len(re.findall(r'\w+',pt))<=3:reasons.append('Short emotional call: acting cannot be inferred from text or emotion flag')
            if u.get('source_speaker','unknown')=='unknown':reasons.append('Original identity remains unknown; no new casting/synthesis in this pilot')
            if any(u['screening_candidates'].values()):reasons.append('Orthographic pronunciation features available for native listening; not phonetic diagnosis')
            if reasons:rows.append({'episode':ep['episode'],'unit_id':u['id'],'cue_ids':u['cue_ids'],
              'source_text':u['source_text'],'translation':u['translation'],'review_candidates':reasons})
    save_json(ROOT/'whole-season-triage.private.json',{'source_manifest_sha256':digest(baseline.ROOT/'manifest.private.json'),
      'examined_episodes':32,'examined_units':556,'candidate_units':len(rows),'rows':rows,
      'voice_configuration_by_role':base['whole_season_stats']['voice_configuration_by_role'],
      'policy':'Screening queue, not confirmed errors, native review or automated permission to rewrite all episodes'})


def prepare():
    m=build_manifest();path=ROOT/'manifest.private.json'
    if path.exists() and read_json(path)!=m:raise ValueError('Use a new audited pilot version, do not overwrite paid scope')
    bind(ROOT/'manifest-fingerprint.json',m)
    if not path.exists():save_json(path,m)
    validate(m,False)
    from contextual_ptbr_render import subtitle_rows
    for s in m['scenes']:subtitle_rows(s)
    triage();print('CONTEXTUAL_PREPARED',34,len(known_groups(m)),flush=True)


def known_groups(m):return [g for s in m['scenes'] for g in s['groups'] if g['request'] is not None]


def preflight(m):
    requests={fingerprint(g['request']):g['request'] for g in known_groups(m)};found={k:[] for k in requests}
    aliases={alias:(key,variant) for key,req in requests.items() for alias,variant in numeric_request_variants(req).items()}
    roots=list(dict.fromkeys(paid_cache_roots()+[Path('output/drama-01'),Path('output/clone-feedback-20261021/requests'),
      Path('output/clone-feedback-20261024/requests'),PARENT_ROOT/'requests',ROOT/'requests']))
    for root in roots:
        for pending in root.rglob('*.submission-pending.json'):
            accepted=pending.with_name(pending.name.removesuffix('.submission-pending.json')+'.json')
            if not accepted.exists() or not read_json(accepted).get('taskId'):raise ValueError('Unknown paid submission: reconcile before new requests')
        for marker in root.rglob('request-fingerprint.json'):
            key=read_json(marker).get('fingerprint')
            if key in aliases:
                canonical,variant=aliases[key];found[canonical].append((marker.parent,variant))
    selected={};receipt_requests={}
    for key,req in requests.items():
        target=ROOT/'requests'/key
        old=[(p,v) for p,v in found[key] if p!=target]
        for p,v in old:completed(p,v) # An old incomplete matching request must be reconciled, not bypassed.
        folder,receipt_req=old[0] if old else (target,req)
        pin=m.get('timing_revision_basis',{}).get('preferred_parent_audio',{}).get(key)
        if pin:
            folder=Path(pin['path']).parent;receipt_req=req
            _,receipt=completed(folder,receipt_req)
            if receipt['sha256']!=pin['sha256'] or receipt['task_id']!=pin['task_id']:raise ValueError('Exact parent recording changed')
        if (folder/'audio-receipt.json').exists():completed(folder,receipt_req)
        selected[key]=folder;receipt_requests[key]=receipt_req
    save_json(ROOT/'cache-preflight.private.json',{'selected':{k:str(v) for k,v in selected.items()},
      'unique_request_count':len(requests),'new_clone_count':0,
      'receipt_requests':receipt_requests,
      'completed_exact_matches':sum((p/'audio-receipt.json').exists() for p in selected.values())})
    return selected


def synthesize(m,config,ffmpeg):
    import numpy as np
    validate(m)
    if (ROOT/'generation-result.private.json').exists():
        generated(m);print('CONTEXT_GENERATION_COMPLETE_REUSED',flush=True);return
    selected=preflight(m);requests={fingerprint(g['request']):g['request'] for g in known_groups(m)}
    receipt_requests=read_json(ROOT/'cache-preflight.private.json')['receipt_requests']
    if TIMING_REVISION and sum(not (p/'audio-receipt.json').exists() for p in selected.values())>2:
        raise ValueError('Only two new timing requests may be submitted')
    results={};client=None;new=0
    for key,req in requests.items():
        folder=selected[key];reused=(folder/'audio-receipt.json').exists()
        cache_req=receipt_requests[key]
        if reused:path,receipt=completed(folder,cache_req)
        else:
            if not (folder/'submission.private.json').exists():new+=1
            if new>m['paid_request_cap']:raise ValueError('Paid request bound exceeded')
            if client is None:client=Mflix(config)
            path,receipt=generate(client,req,folder)
        samples=read_audio(path,ffmpeg)
        if not len(samples) or not np.isfinite(samples).all() or float(np.max(np.abs(samples)))<1e-5:
            raise ValueError('Paid audio is empty/nonfinite/silent; preserve receipt and inspect, never resubmit automatically')
        results[key]={'request':req,'path':str(path),'sha256':digest(path),'task_id':receipt['task_id'],
          'duration_seconds':len(samples)/RATE,'reused_completed_audio':reused,'receipt_request':cache_req}
        save_json(ROOT/'generation-progress.private.json',results)
        print('CONTEXT_AUDIO_READY',len(results),len(requests),'REUSED' if reused else 'NEW',flush=True)
    save_json(ROOT/'generation-result.private.json',{'results':results,'new_clone_count':0})


def generated(m):
    validate(m);g=read_json(ROOT/'generation-result.private.json')['results']
    expected={fingerprint(u['request']):u['request'] for u in known_groups(m)}
    if set(g)!=set(expected):raise ValueError('Incomplete contextual generation')
    for key,req in expected.items():
        r=g[key]
        if r['request']!=req or digest(r['path'])!=r['sha256']:raise ValueError('Generated audio changed')
        cache_req=r.get('receipt_request',req)
        if fingerprint(cache_req) not in numeric_request_variants(req):raise ValueError('Cache request is not strictly numerically equivalent')
        _,receipt=completed(Path(r['path']).parent,cache_req)
        if receipt['task_id']!=r['task_id']:raise ValueError('Task binding changed')
    return g


def screen(m,ffmpeg):
    import subprocess
    import numpy as np
    from faster_whisper import WhisperModel
    g=generated(m);local=Path('output/tools/source-asr-models/large-v3')
    official=read_json(local/'official-source.json');v=read_json(local/'verified.json')
    sha=next(f['lfs']['sha256'] for f in official['siblings'] if f['rfilename']=='model.bin')
    if (v.get('official_hashes_verified') is not True or v['revision']!=official['revision']
      or v['repo']!='Systran/faster-whisper-large-v3' or digest(local/'model.bin')!=sha):raise ValueError('Pinned ASR source required')
    model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
    decoding={'language':'pt','beam_size':5,'temperature':0,'condition_on_previous_text':False,'vad_filter':False};rows=[]
    for u in known_groups(m):
        r=g[fingerprint(u['request'])];p=ROOT/'content-screening'/f'{u["id"]}.private.json'
        if p.exists():
            record=read_json(p)
            if record['audio_sha256']!=r['sha256'] or record['expected_text']!=u['caption'] or record['decoding']!=decoding:raise ValueError('Screening changed')
        else:
            raw=subprocess.run([str(ffmpeg),'-v','error','-i',r['path'],'-f','f32le','-ar','16000','-ac','1','pipe:1'],check=True,capture_output=True)
            segments,_=model.transcribe(np.frombuffer(raw.stdout,dtype='<f4'),**decoding)
            record={'unit_id':u['id'],'audio_sha256':r['sha256'],'expected_text':u['caption'],
              'asr_transcript':' '.join(s.text.strip() for s in segments),'decoding':decoding,'model_revision':v['revision'],
              'native_listening_passed':False}
            save_json(p,record)
        rows.append(record);print('CONTEXT_SCREENED',len(rows),len(known_groups(m)),flush=True)
    save_json(ROOT/'content-screening.private.json',{'results':rows,'native_listening_passed':False})


def fit(m,ffmpeg):
    g=generated(m);rows=[];blocked=[]
    for s in m['scenes']:
        for u in s['groups']:
            if u['request'] is None:
                rows.append({'unit_id':u['id'],'unknown_retained':u['unknown_retained'],
                  'same_clone_original_retained':u.get('same_clone_original_retained',False),'source_unit_ids':u['source_unit_ids']});continue
            r=g[fingerprint(u['request'])];target=u['audio_end_limit']-u['start'];natural=r['duration_seconds']
            if natural>target*1.2+1e-6:
                blocked.append({'unit_id':u['id'],'natural_seconds':natural,'target_seconds':target,'maximum_natural_seconds':target*1.2});continue
            out=ROOT/'fitted'/f'{u["id"]}.wav';out.parent.mkdir(exist_ok=True)
            try:
                samples,factor=fit_speech(Path(r['path']),out,target,max(1.,natural/target),ffmpeg)
            except ValueError:
                blocked.append({'unit_id':u['id'],'natural_seconds':natural,'target_seconds':target,
                  'reason':'Actual fitted frames exceed the fixed timing/speed policy; raw audio retained, no paid retry'})
                continue
            rows.append({'unit_id':u['id'],'path':str(out),'sha256':digest(out),'start':u['start'],
              'duration_seconds':len(samples)/RATE,'atempo_factor':factor,'raw_sha256':r['sha256'],
              'target_seconds':target,'audio_end_limit':u['audio_end_limit'],'unknown_retained':False})
    save_json(ROOT/'fit-report.private.json',{'units':rows,'blocked':blocked,'ready':not blocked,
      'manifest_sha256':digest(ROOT/'manifest.private.json'),'generation_sha256':digest(ROOT/'generation-result.private.json'),
      'no_speech_truncated':True,'no_paid_retry':True})
    print('CONTEXT_FITTED',len(rows),'BLOCKED',len(blocked),flush=True)
    if blocked:raise SystemExit(2)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',required=True,choices=['prepare','preflight','generate','screen','fit','render','publish'])
    p.add_argument('--ffmpeg',type=Path);p.add_argument('--mcp-config',type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Execute material processing on Windows')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/('screening.lock' if a.stage=='screen' else 'pipeline.lock'),timeout=0):
        if a.stage=='prepare':prepare();return
        m=read_json(ROOT/'manifest.private.json');validate(m)
        if a.stage=='preflight':preflight(m);print('CONTEXT_PREFLIGHT_OK',flush=True)
        elif a.stage=='generate':synthesize(m,a.mcp_config,a.ffmpeg)
        elif a.stage=='screen':screen(m,a.ffmpeg)
        elif a.stage=='fit':fit(m,a.ffmpeg)
        elif a.stage=='render':
            from contextual_ptbr_render import render
            render(m,a.ffmpeg)
        else:
            from contextual_ptbr_render import publish
            publish(m,a.mcp_config)


if __name__=='__main__':main()
