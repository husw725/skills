"""Isolated full-season revision, authorized after EP02 feedback; Windows execution only."""
import argparse
import copy
import html
import json
import math
from pathlib import Path
import re
import sys
import time

from audit_series_readiness import source_binding_matches, split_provenance_issues, contains
from cartesia_pilot import bind, speech_request
from codex_translate_episode import call_codex
from dub_episode import RATE, digest, probe, read_audio, run, trim_edges, tts_request, write_audio
from mflix_client import Mflix
from process_lock import process_lock
from repair_episode_feedback import generate, request_for
from screenplay_context import load_screenplay_context
from translate import fingerprint, read_json, save_json, validate_bible, write_srt

ROOT = Path('output/carmilla-season-revision-20261016')
BASE_ROOT = ROOT
RETRY_ROOT = Path('output/carmilla-season-revision-20261017-retry1')
ROLES = {'Laura','Carmilla','Father','Irina','Woodsman','Mother','Narrator_EP01','Narrator_EP03'}
STORYBOARD_MAPPING_SHA256 = '6efd76bfd6d0227e0d8a00dea6ca0d3e4132d87d0042e91aa39f56128ad0bb38'


def response_schema():
    issue={'type':'object','properties':{'severity':{'type':'string','enum':['warning','error']},
           'reason':{'type':'string'}},'required':['severity','reason'],'additionalProperties':False}
    cue = {'type':'object','properties':{'id':{'type':'string'},'translation':{'type':'string'},
           'emotion':{'type':'string','enum':['calm','fearful','angry','sad','happy','surprised','disgusted']},
           'script_evidence':{'type':'string'}, 'issues':{'type':'array','items':issue}},
           'required':['id','translation','emotion','script_evidence','issues'],'additionalProperties':False}
    return {'type':'object','properties':{'cues':{'type':'array','items':cue},
            'groups':{'type':'array','items':{'type':'array','items':{'type':'string'}}},
            'consistency_notes':{'type':'array','items':{'type':'string'}}},
            'required':['cues','groups','consistency_notes'],'additionalProperties':False}


def validate_editorial(data, rows, old, annotations, glossary):
    ids=[r['id'] for r in rows]
    if [r['id'] for r in data['cues']] != ids: raise ValueError('Editorial cue IDs/order changed')
    covered=[c for g in data['groups'] for c in g]
    if covered != ids or any(not g for g in data['groups']): raise ValueError('Grouping coverage/order differs')
    positions={c:i for i,c in enumerate(ids)}
    for cue,row in zip(data['cues'],rows):
        if not cue['translation'].strip() or not cue['script_evidence'].strip(): raise ValueError('Missing editorial text/evidence')
        for issue in cue.get('issues',[]):
            if not isinstance(issue,dict) or issue.get('severity') not in ('warning','error') or not issue.get('reason'):
                raise ValueError('Editorial issue must distinguish blocking error from listening warning')
            if issue['severity']=='error':raise ValueError('Unresolved textual/source error; no synthesis permitted')
        for source,target in glossary.items():
            if contains(row['text'],source) and not contains(cue['translation'],target):
                raise ValueError('Locked name/term missing; review whole thought before proceeding')
    for group in data['groups']:
        members=[rows[positions[c]] for c in group]
        speakers={annotations[c]['speaker'] for c in group}
        if len(speakers)!=1 or len({old[c]['production_voice'] for c in group})!=1:
            raise ValueError('Cannot group across speakers/production voices')
        if 'unknown' in speakers and len({old[c]['id'] for c in group})>1:
            raise ValueError('Unknown readers cannot be inferred identical from voice casting')
        if any(b['start']<a['end'] or b['start']-a['end']>.6 for a,b in zip(members,members[1:])):
            raise ValueError('Grouping crosses overlap/long pause')
        by_cue={c['id']:c for c in data['cues']}
        if len({by_cue[c]['emotion'] for c in group})!=1:
            raise ValueError('Separate changes of performance direction before synthesis')


def sources(n):
    ep=Path(f'output/drama-01/episode-{n:02}')
    plan=ep/'dub-plan-v1.json'
    source=ep/('script-revision-input/episode-01.source.json' if n==1 else 'editorial/source.json')
    context=ep/('translation-v2/screenplay-context.json' if n==1 else 'editorial/screenplay-context.json')
    return plan,source,context


def storyboard_reference(n, content):
    # The user supplied 33 storyboard entries for 32 released episodes. These are
    # dialogue-aligned references, not invented additional source dialogue.
    mapping={i:[f'EP-{i:02}'] for i in range(1,20)}
    mapping.update({i:[f'EP-{i+1:02}'] for i in range(20,31)})
    mapping.update({24:['EP-24','EP-25'],25:['EP-24','EP-26'],31:['EP-32'],32:['EP-32','EP-33']})
    marker='const E='
    if marker not in content:raise ValueError('Unexpected storyboard format; do not execute HTML')
    entries,_=json.JSONDecoder().raw_decode(content[content.index(marker)+len(marker):])
    by_id={e['id']:e for e in entries}
    refs=[]
    for key in mapping[n]:
        entry=by_id[key]
        refs.append({'storyboard_episode':key,'script':html.unescape(re.sub('<[^>]*>',' ',entry['script'])),
                     'storyboard':html.unescape(re.sub('<[^>]*>',' ',entry['storyboard']))})
    return {'mapping_basis':'Prior reviewed context plus exact English dialogue phrase alignment; '
                            'EP24/25/32 overlap entries, so multiple references supplied. Timed source is authoritative.',
            'entries':refs}


def validate_reviewed_plan(folder, plan):
    marker=folder/'reviewed-plan-fingerprint.json'
    if not marker.exists() or read_json(marker).get('fingerprint')!=fingerprint(plan):
        raise ValueError('Plan is not bound to its validated editorial result; no paid synthesis')


def prepare(n,args,preceding):
    folder=ROOT/f'episode-{n:02}';folder.mkdir(parents=True,exist_ok=True)
    plan_path,source_path,context_path=sources(n)
    bible_path=Path('output/drama-01/episode-01/translation-v2/series-bible.json')
    storyboard=Path('input/drama-01/storyboard/final.html')
    inputs={str(p):digest(p) for p in (plan_path,source_path,context_path,bible_path,storyboard)}
    if inputs[str(storyboard)]!=STORYBOARD_MAPPING_SHA256:
        raise ValueError('Storyboard changed; recheck the 33-to-32 dialogue mapping before revision')
    plan=read_json(plan_path);rows=read_json(source_path)['segments'];context=load_screenplay_context(context_path,rows)
    for ref in context['sources']:
        name=Path(ref['filename']).name
        candidates=[p/name for p in (Path('input/drama-01/screenplay'),Path('input/drama-01/storyboard')) if (p/name).is_file()]
        if len(candidates)!=1 or digest(candidates[0])!=ref['sha256']:
            raise ValueError('Physical screenplay/storyboard file differs from reviewed provenance')
        inputs[str(candidates[0])]=ref['sha256']
    if (plan['project_id'],plan['episode'])!=(59,n): raise ValueError('Original plan scope changed')
    annotations=context['episodes'][str(n)]['cue_annotations'];by_id={r['id']:r for r in rows}
    if split_provenance_issues(rows): raise ValueError('Split subtitle provenance requires review')
    old={c:u for u in plan['units'] for c in u['cue_ids']}
    if len(old)!=len(rows) or set(old)!=set(by_id): raise ValueError('Source coverage differs')
    if any(not source_binding_matches(u,by_id,annotations) for u in plan['units']):
        raise ValueError('Original screenplay/source binding changed')
    if any(u['production_voice'] not in ROLES for u in plan['units']): raise ValueError('Unexpected role')
    bible=read_json(bible_path);glossary=validate_bible(bible)
    payload={'episode':n,'locked_bible':bible,'reviewed_screenplay_context':context,
             'user_storyboard_sha256':inputs[str(storyboard)],
             'user_storyboard_reference':storyboard_reference(n,storyboard.read_text(encoding='utf-8-sig')),'timed_source':rows,
             'previous_episode_revisions':preceding[-2:],
             'old_translation_reference':[{'cue_ids':u['cue_ids'],'text':u['translation']} for u in plan['units']],
             'production_voice_per_cue':{c:u['production_voice'] for c,u in old.items()},
             'known_issue':'EP29 e29-8 source How many years. conflicts with screenplay minions; retain original text and flag for original-audio verification, never silently replace it.'}
    if getattr(args,'prior_root',None):
        payload['revision_feedback']=revision_feedback(n,args,preceding)
        payload['previous_episode_revisions']=payload['revision_feedback'].pop('previous_episode_revisions')
        inputs.update(payload['revision_feedback']['source_sha256'])
    bind(folder/'editorial-input.json',{'sha256':inputs,'context':payload,'policy_version':1})
    schema=folder/'schema.json';save_json(schema,response_schema())
    prompt=('Revise this entire episode into natural spoken Brazilian Portuguese with screenplay context. '
            'Preserve meaning, names, negation, relationship, deadlines and original cue IDs/order/times. '
            'Do not invent dialogue from the screenplay or silently fix uncertain ASR. Keep unknown evidence readers unknown. '
            'The user storyboard is reference only and has 33 entries for 32 videos: do not assume episode numbers align. '
            'Keep correct existing wording where suitable; improve awkward language or overly long phrasing faithfully. '
            'Translate complete thoughts, distribute wording across their original cues, and propose adjacent same-speaker '
            'groups for natural delivery; groups cover ALL cues once, including singleton groups. Gap <=0.6s. '
            'Keep changes of emotion/performance direction in separate groups. '
            'Unknown readers may share a group only if already in the same original production unit. '
            'Do not mechanically add ellipses at subtitle boundaries. Use punctuation for actual performance. '
            'EP02 professional feedback: anos sounded European, não sounded English and lacked a fearful scream. '
            'Those are AUDIO issues: do not corrupt correct spelling or claim textual edits verify accent/emotion. '
            'No new feedback on the three diagnostic candidates is available; do not claim those methods passed. '
            'Mark unresolved semantic/source/cut errors as severity error; only audio/listening uncertainty is warning. '
            'When revision_feedback is supplied, review every prior issue individually. Timed dialogue is authoritative: '
            'a screenplay-only extra clause, plot inconsistency shared by both sources, or unknown evidence reader '
            'does not by itself make a faithful translation invalid. Keep those as documented warnings if wording is clear. '
            'True ambiguous words, negation, referents, source/cut mismatch or unexplained speaker conflicts remain errors. '
            'Never mark source audio verified. For measured overlong groups, shorten faithfully or regroup only within '
            'the existing speaker/timing constraints. Preserve complete meaning and all deadlines/names. '
            'Aim for a margin below the provided maximum_seconds; do not assume synthesized duration is verified. '
            'Keep prior correct wording for unaffected cues to reuse paid audio. '
            'Consult the supplied inline context and mapped storyboard references. Do not call MCP, clone/TTS/upload, edit files, '
            'change source/casting or credentials. Return only structured data.\n'+__import__('json').dumps(payload,ensure_ascii=False))
    draft_path=folder/'draft.json'
    draft=read_json(draft_path) if draft_path.exists() else call_codex(args.codex_exe,prompt,schema,draft_path,folder/'draft.private.log')
    # Validate structural/casting constraints after review, allowing draft defects to be repaired.
    reviewed_path=folder/'reviewed.json'
    reviewed=read_json(reviewed_path) if reviewed_path.exists() else call_codex(args.codex_exe,
        prompt+'\nPerform a second semantic and continuity review, correct the candidate, verify all grouping constraints.\n'+
        __import__('json').dumps(draft,ensure_ascii=False),schema,reviewed_path,folder/'review.private.log')
    validate_editorial(reviewed,rows,old,annotations,glossary)
    if any(digest(Path(p))!=sha for p,sha in inputs.items()): raise ValueError('Editorial inputs changed')
    revised_context=copy.deepcopy(context)
    revised_context['revision_basis']={'original_context_sha256':inputs[str(context_path)],'policy':'EP02-feedback full-season rerun; no native listening approval'}
    new_annotations=revised_context['episodes'][str(n)]['cue_annotations']
    for row,cue in zip(rows,reviewed['cues']):
        new_annotations[row['id']]['emotion_intent']=cue['emotion']
        new_annotations[row['id']]['editorial_review_evidence']=cue['script_evidence']
    save_json(folder/'screenplay-context.json',revised_context)
    translated=[{**r,'translation':c['translation']} for r,c in zip(rows,reviewed['cues'])]
    save_json(folder/'translation.json',{'segments':translated,'native_listening_passed':False})
    write_srt(folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt',translated)
    units=[];cue_map={r['id']:r for r in reviewed['cues']}
    for index,group in enumerate(reviewed['groups']):
        members=[by_id[c] for c in group];cs=[cue_map[c] for c in group]
        units.append({'id':f'e{n:02}-group-{index+1:03}','cue_ids':group,'start':members[0]['start'],'end':members[-1]['end'],
                      'source_text':' '.join(r['text'] for r in members),'translation':' '.join(c['translation'] for c in cs),
                      'production_voice':old[group[0]]['production_voice'],'source_speaker':annotations[group[0]]['speaker'],
                      'emotion':cs[0]['emotion'],'emotion_transitions':[c['emotion'] for c in cs],
                      'source_windows':[{k:r[k] for k in ('id','start','end')} for r in members],
                      'issues':[issue for c in cs for issue in c['issues']]})
    new_plan={'episode':n,'project_id':59,'assets':plan['assets'],'units':units,'input_sha256':inputs,
              'reviewed_context_sha256':digest(folder/'screenplay-context.json'),
              'reviewed_response_sha256':digest(reviewed_path),'translation_srt_sha256':digest(folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt'),
              'blocking_issues':['Original audio verification required for e29-8 before complete new episode release'] if n==29 else []}
    bind(folder/'reviewed-plan-fingerprint.json',new_plan)
    save_json(folder/'plan.json',new_plan)
    return {'episode':n,'cues':reviewed['cues'],'consistency_notes':reviewed['consistency_notes']}


def revision_feedback(n,args,preceding=()):
    prior=Path(args.prior_root)
    if prior.resolve()!=BASE_ROOT.resolve():raise ValueError('Only the existing season may seed this retry')
    folder=prior/f'episode-{n:02}'
    continuity={int(row['episode']):row for row in preceding[-2:]}
    data={'source_root':str(prior),'source_sha256':{},'prior_editorial':None,'measured_groups':[]}
    for previous in range(max(1,n-2),n):
        ep=prior/f'episode-{previous:02}'
        if previous in continuity or not (ep/'render-report.json').exists():continue
        p=read_json(ep/'plan.json');validate_reviewed_plan(ep,p)
        if digest(ep/'reviewed.json')!=p['reviewed_response_sha256']:
            raise ValueError('Prior completed episode editorial changed')
        reviewed=read_json(ep/'reviewed.json')
        continuity[previous]={'episode':previous,'cues':reviewed['cues'],'consistency_notes':reviewed['consistency_notes'],
                              'native_listening_approved':False}
        for name in ('plan.json','reviewed.json','render-report.json'):
            data['source_sha256'][str(ep/name)]=digest(ep/name)
    data['previous_episode_revisions']=[continuity[k] for k in sorted(continuity)[-2:]]
    for name in ('reviewed.json','plan.json'):
        p=folder/name
        if p.exists():data['source_sha256'][str(p)]=digest(p)
    if (folder/'reviewed.json').exists():data['prior_editorial']=read_json(folder/'reviewed.json')
    if not (folder/'plan.json').exists():return data
    plan=read_json(folder/'plan.json');validate_reviewed_plan(folder,plan)
    duration=float(probe(Path(plan['assets']['video']),args.ffmpeg)['format']['duration'])
    for i,u in enumerate(plan['units']):
        wav=folder/'utterances'/u['id']/'original.wav'
        receipt=wav.parent/'audio-receipt.json'
        if not wav.exists():continue
        if not receipt.exists() or digest(wav)!=read_json(receipt)['sha256']:
            raise ValueError('Prior paid audio receipt missing or changed; inspect before retry')
        data['source_sha256'][str(wav)]=digest(wav)
        data['source_sha256'][str(receipt)]=digest(receipt)
        samples,_,_=trim_edges(read_audio(wav,args.ffmpeg));natural=len(samples)/RATE
        following=plan['units'][i+1]['start'] if i+1<len(plan['units']) else duration
        end=max(u['end'],min(duration,following-.1,u['end']+.8))
        maximum=(end-u['start'])*1.2
        data['measured_groups'].append({'cue_ids':u['cue_ids'],'translation':u['translation'],
            'natural_seconds':natural,'maximum_seconds':maximum,'requires_shortening':natural>maximum,
            'audio_sha256':read_json(receipt)['sha256']})
    if any(digest(Path(p))!=sha for p,sha in data['source_sha256'].items()):
        raise ValueError('Prior revision changed while collecting feedback')
    return data


def paid_audio_folder(n,req,target,prior_root=None):
    """Reuse the exact prior request, including ambiguous receipts; never route around them."""
    if prior_root is None:return target
    prior=Path(prior_root)
    if prior.resolve()!=BASE_ROOT.resolve():raise ValueError('Unexpected paid cache root')
    # A changed text must not bypass an ambiguous earlier payment. Check the
    # entire original episode, even when its request marker is missing.
    for pending in (prior/f'episode-{n:02}'/'utterances').rglob('*.submission-pending.json'):
        accepted=pending.with_name(pending.name.removesuffix('.submission-pending.json')+'.json')
        if not accepted.exists() or not read_json(accepted).get('taskId'):
            raise ValueError('Ambiguous prior paid request; reconcile before retry')
    matches=[]
    for marker in sorted((prior/f'episode-{n:02}'/'utterances').glob('*/request-fingerprint.json')):
        if read_json(marker).get('fingerprint')==fingerprint(req):matches.append(marker.parent)
    return matches[0] if matches else target


def request(unit,cartesia,minimax):
    role=unit['production_voice'];text=unit['translation']
    if role not in ROLES: raise ValueError('Unknown production role; no cloning allowed')
    fearful_no=(unit['emotion']=='fearful' and re.findall(r'\w+',text.casefold())==['não'])
    if role in ('Laura','Carmilla') and not fearful_no:
        return speech_request(text,cartesia[role]['voice_id'],59),'cartesia'
    voice=minimax[role]['voice_id']
    if not isinstance(voice,str) or not voice or voice.startswith('cartesia:'):
        raise ValueError('Existing MiniMax role voice required; no new clone fallback')
    if fearful_no:
        # Phonetic control stays exclusively in the synthesis layer; spelling/SRT unchanged.
        synthesis='(gasps)(nɐ̃w̃)!' if unit['cue_ids']==['e02-16'] else '(nɐ̃w̃)!'
        return request_for(synthesis,voice,59),'minimax-fearful-no-candidate'
    req=tts_request({'translation':text,'emotion':unit['emotion']},voice,59,1.0,unit['emotion'])
    req.pop('referenceAudioList',None);req.update({'language':None,'outputFormat':None})
    return req,'minimax'


def render(n,args):
    folder=ROOT/f'episode-{n:02}';plan=read_json(folder/'plan.json')
    validate_reviewed_plan(folder,plan)
    if plan['blocking_issues']: raise ValueError('Source dialogue requires verification; do not disguise it by regenerating')
    cartesia_path=Path('output/drama-01/cartesia-pilot-voices/voice-bank.json');minimax_path=Path('output/drama-01/voice-bank.json')
    cartesia=read_json(cartesia_path);minimax=read_json(minimax_path)['voices']
    if not ROLES.issubset(minimax) or not {'Laura','Carmilla'}.issubset(cartesia):
        raise ValueError('Incomplete existing role bank; do not create new voices')
    bind(ROOT/'frozen-voice-policy.json',{'cartesia':cartesia,'minimax':minimax,
         'main_cartesia_roles':['Laura','Carmilla'],'short_fearful_no':'existing-role-minimax',
         'tts_speed':1.0,'max_atempo':1.2,'cloning_enabled':False})
    if getattr(args,'prior_root',None):
        prior_policy=Path(args.prior_root)/'frozen-voice-policy.json'
        if not prior_policy.exists() or read_json(prior_policy)!=read_json(ROOT/'frozen-voice-policy.json'):
            raise ValueError('Existing voice policy changed; no payment permitted')
    if (plan['project_id'],plan['episode'])!=(59,n): raise ValueError('Revision scope differs')
    for p,sha in plan['input_sha256'].items():
        if digest(Path(p))!=sha: raise ValueError('Original inputs changed after review')
    for filename,key in [('screenplay-context.json','reviewed_context_sha256'),('reviewed.json','reviewed_response_sha256'),
                         (f'Carmilla_EP{n:02}_pt-BR_revised.srt','translation_srt_sha256')]:
        if digest(folder/filename)!=plan[key]: raise ValueError('Reviewed revision changed')
    requests=[request(u,cartesia,minimax) for u in plan['units']]  # preflight ALL role IDs before paid work
    assets={k:Path(v) for k,v in plan['assets'].items()};asset_hashes={k:digest(p) for k,p in assets.items()}
    duration=float(probe(assets['video'],args.ffmpeg)['format']['duration'])
    if (any(u['start']<0 or u['end']<=u['start'] or u['end']>duration for u in plan['units'])
            or any(a['end']>b['start'] for a,b in zip(plan['units'],plan['units'][1:]))):
        raise ValueError('Invalid or overlapping source group windows before paid work')
    bind(folder/'render-input.json',{'plan':plan,'asset_hashes':asset_hashes,'requests':requests,
          'cartesia_bank_sha256':digest(cartesia_path),'minimax_bank_sha256':digest(minimax_path),
          'max_atempo':1.2,'max_post_subtitle_gap_seconds':.8,'cloning_enabled':False})
    client=Mflix(args.mcp_config);results=[]
    for index,(unit,(req,provider)) in enumerate(zip(plan['units'],requests)):
        target_dir=folder/'utterances'/unit['id']
        cached=paid_audio_folder(n,req,target_dir,getattr(args,'prior_root',None))
        path,receipt=generate(client,req,cached)
        target_dir.mkdir(parents=True,exist_ok=True)
        samples,_,_=trim_edges(read_audio(path,args.ffmpeg));natural=len(samples)/RATE
        next_start=plan['units'][index+1]['start'] if index+1<len(plan['units']) else duration
        limit=min(duration,next_start-.1,unit['end']+.8)
        if limit<unit['end']-.001: limit=unit['end']
        target=max(unit['end'],min(limit,unit['start']+natural))-unit['start']
        factor=max(1.,natural/target)
        if factor>1.2: raise ValueError('Measured speech too long: revise faithfully; no automatic paid speed retries')
        trimmed,fitted=target_dir/'trimmed.wav',target_dir/'fitted.wav';write_audio(trimmed,samples)
        for _ in range(4):
            run([args.ffmpeg,'-v','error','-y','-i',trimmed,'-af',f'atempo={factor:.8f}',
                 '-ar',str(RATE),'-ac','1','-c:a','pcm_s16le',fitted])
            audio=read_audio(fitted,args.ffmpeg)
            if len(audio)<=math.floor(target*RATE): break
            factor*=len(audio)/(target*RATE)*1.005
        if factor>1.2 or len(audio)>math.floor(target*RATE): raise ValueError('Cannot fit without truncating/over-speeding')
        results.append({**unit,'provider':provider,'task_id':receipt['task_id'],'request':req,'atempo_factor':factor,
                        'paid_audio_reused_from_prior_attempt':cached!=target_dir,
                        'natural_duration_seconds':natural,'fitted_duration_seconds':len(audio)/RATE,
                        'post_subtitle_gap_used_seconds':max(0,unit['start']+len(audio)/RATE-unit['end']),
                        'fitted_path':str(fitted),'fitted_sha256':digest(fitted),'native_listening_passed':False})
        save_json(folder/'progress.json',{'episode':n,'stage':'synthesizing','complete':len(results),'total':len(requests),'updated_at':time.time()})
    import numpy as np
    dialogue=np.zeros(math.ceil(duration*RATE),dtype=np.float32)
    for r in results:
        audio=read_audio(Path(r['fitted_path']),args.ffmpeg);start=round(r['start']*RATE)
        if start+len(audio)>len(dialogue): raise ValueError('Dialogue exceeds video')
        dialogue[start:start+len(audio)]+=audio
    d,m=folder/'dialogue-ptBR.wav',folder/'mix-ptBR.wav';write_audio(d,dialogue)
    if any(digest(p)!=asset_hashes[k] for k,p in assets.items()): raise ValueError('Original media changed')
    run([args.ffmpeg,'-v','error','-y','-i',d,'-i',assets['bgm'],'-i',assets['sfx'],'-filter_complex',
         f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[2:a]apad,atrim=duration={duration}[s];[d][b][s]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
         '-map','[out]','-ar',str(RATE),'-ac','2','-c:a','pcm_s16le',m])
    final=folder/f'Carmilla_EP{n:02}_pt-BR_season-revision.mp4'
    run([args.ffmpeg,'-v','error','-y','-i',assets['video'],'-i',m,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',final])
    run([args.ffmpeg,'-v','error','-xerror','-i',final,'-f','null','-'])
    hashes=[run([args.ffmpeg,'-v','error','-i',p,'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip() for p in (assets['video'],final)]
    if hashes[0]!=hashes[1]: raise ValueError('Video payload changed')
    save_json(folder/'render-report.json',{'episode':n,'status':'rendered_season_revision_candidate','output':str(final),
        'output_sha256':digest(final),'video_payload_identical':True,'source_audio_in_output':False,'new_clone_count':0,
        'tts_task_count':len(results),'prior_attempt_audio_reused_count':sum(r['paid_audio_reused_from_prior_attempt'] for r in results),
        'native_ptBR_listening_reviewed':False,'performance_verified':False,
        'mixed_model_timbre_review_required':True,'source_speaker_unknown_preserved':True,
        'mix_source_isolation_review_required':n in (13,31),'utterances':results})


def main():
    global ROOT
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=('editorial','render','all'),default='all')
    p.add_argument('--codex-exe',type=Path);p.add_argument('--mcp-config',type=Path);p.add_argument('--ffmpeg',type=Path)
    p.add_argument('--retry-pending',action='store_true',help='Isolated second attempt using measured feedback and exact paid-request reuse')
    a=p.parse_args()
    if sys.platform!='win32':p.error('All business execution remains on Windows')
    if a.stage in ('editorial','all') and (not a.codex_exe or not a.codex_exe.is_file()):p.error('Existing native Codex executable required')
    if a.stage in ('render','all') and (not a.mcp_config or not a.ffmpeg or not a.ffmpeg.is_file()):p.error('Production config/ffmpeg required')
    episodes=list(range(1,33));a.prior_root=None
    if a.retry_pending:
        if not a.ffmpeg or not a.ffmpeg.is_file():p.error('Measured retry needs FFmpeg')
        a.prior_root=BASE_ROOT;ROOT=RETRY_ROOT
    ROOT.mkdir(parents=True,exist_ok=True)
    # Share the original season lock so an old runner cannot submit in parallel.
    with process_lock(BASE_ROOT/'season.lock',timeout=0):
        if a.retry_pending:
            baseline=read_json(BASE_ROOT/'season-progress.json')
            if set(baseline['episodes'])!={str(i) for i in range(1,33)}:p.error('Incomplete prior season status')
            episodes=[n for n in episodes if baseline['episodes'][str(n)]['stage']=='requires_review']
            if not episodes:p.error('No pending episodes to retry')
        state={'authorized_scope':'Carmilla 32 episode rerun using existing EP02 feedback; no waiting for diagnostic reviews',
               'selected_episodes':episodes,'native_acceptance_passed':False,'episodes':{}};preceding=[]
        if a.stage in ('editorial','all'):
            for n in episodes:
                try:
                    preceding.append(prepare(n,a,preceding))
                    state['episodes'][str(n)]={'stage':'editorial_ready'}
                except Exception as exc:
                    state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                    print('EDITORIAL_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
                state['updated_at']=time.time();save_json(ROOT/'season-progress.json',state)
        if a.stage in ('render','all'):
            for n in episodes:
                if a.stage=='all' and state['episodes'][str(n)]['stage']!='editorial_ready':continue
                try:
                    with process_lock(ROOT/f'episode-{n:02}'/'render.lock',timeout=0):render(n,a)
                    state['episodes'][str(n)]={'stage':'rendered_candidate'}
                except Exception as exc:
                    state['episodes'][str(n)]={'stage':'requires_review','reason':type(exc).__name__,'detail':str(exc)}
                    print('RENDER_REQUIRES_REVIEW',n,type(exc).__name__,flush=True)
                state['updated_at']=time.time();save_json(ROOT/'season-progress.json',state)
        expected='editorial_ready' if a.stage=='editorial' else 'rendered_candidate'
        complete='editorial_complete' if a.stage=='editorial' else ('selected_candidates_complete' if a.retry_pending else 'complete_candidates')
        state['stage']=complete if all(e['stage']==expected for e in state['episodes'].values()) else 'requires_review'
        save_json(ROOT/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
