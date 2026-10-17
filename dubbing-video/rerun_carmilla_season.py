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
FINAL_ROOT = Path('output/carmilla-season-final-20261017')
TIMING_ROOT = Path('output/carmilla-season-timing-repair-20261017')
ROLES = {'Laura','Carmilla','Father','Irina','Woodsman','Mother','Narrator_EP01','Narrator_EP03'}
STORYBOARD_MAPPING_SHA256 = '6efd76bfd6d0227e0d8a00dea6ca0d3e4132d87d0042e91aa39f56128ad0bb38'


def response_schema(include_source=False):
    issue={'type':'object','properties':{'severity':{'type':'string','enum':['warning','error']},
           'reason':{'type':'string'}},'required':['severity','reason'],'additionalProperties':False}
    cue = {'type':'object','properties':{'id':{'type':'string'},'translation':{'type':'string'},
           'emotion':{'type':'string','enum':['calm','fearful','angry','sad','happy','surprised','disgusted']},
           'script_evidence':{'type':'string'}, 'issues':{'type':'array','items':issue}},
           'required':['id','translation','emotion','script_evidence','issues'],'additionalProperties':False}
    if include_source:
        cue['properties'].update({'source_audio_reading':{'type':'string'},'source_reading_evidence':{'type':'string'},
            'source_reading_status':{'type':'string','enum':['not_requested','subtitle_confirmed','transcription_corrected','uncertain']}})
        cue['required']+=['source_audio_reading','source_reading_evidence','source_reading_status']
    return {'type':'object','properties':{'cues':{'type':'array','items':cue},
            'groups':{'type':'array','items':{'type':'array','items':{'type':'string'}}},
            'consistency_notes':{'type':'array','items':{'type':'string'}}},
            'required':['cues','groups','consistency_notes'],'additionalProperties':False}


def validate_editorial(data, rows, old, annotations, glossary, max_gap=.6):
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
        if any(b['start']<a['end'] or b['start']-a['end']>max_gap+1e-9 for a,b in zip(members,members[1:])):
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


def reading_tokens(text):
    text=text.casefold().replace('’',"'")
    contractions={"can't":"can not","cannot":"can not","won't":"will not","don't":"do not", "doesn't":"does not",
        "didn't":"did not","isn't":"is not","aren't":"are not","wasn't":"was not","weren't":"were not",
        "i'll":"i will","you'll":"you will","we'll":"we will","they'll":"they will","i'd":"i would",
        "i'm":"i am","it's":"it is","she's":"she is","he's":"he is","you're":"you are","we're":"we are"}
    numbers=dict(zip(map(str,range(21)),['zero','one','two','three','four','five','six','seven','eight','nine','ten',
        'eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty']))
    result=[]
    for token in re.findall(r"[a-z0-9]+(?:'[a-z]+)?",text):result.extend(contractions.get(token,numbers.get(token,token)).split())
    return result


def source_audio_evidence(n,rows,source_audio,prior_root):
    review=read_json(Path(prior_root)/f'episode-{n:02}'/'reviewed.json')
    required={c['id'] for c in review['cues'] if any(i['severity']=='error' for i in c['issues'])}
    result={};source_sha=digest(source_audio);inputs={str(source_audio):source_sha}
    for row in rows:
        if row['id'] not in required:continue
        folder=Path('output/carmilla-source-verification-20261017')/f'episode-{n:02}'/row['id']
        clip=folder/'original-context.wav';records={}
        for model in ('small.en','medium.en'):
            path=folder/f'{model}.context.json';record=read_json(path);data=record['input']
            baseline_path=folder/f'{model}.json';baseline=read_json(baseline_path)
            whole=Path(data['whole_episode_evidence']);full=read_json(whole)
            if any(full['input'].get(key)!=data.get(key) for key in ('method','model','model_files','source_audio_sha256','decoding')):
                raise ValueError('Whole-episode evidence source/model mismatch')
            expected=[s for s in full['segments'] if s['end']>=row['start']-1 and s['start']<=row['end']+1]
            if record['segments']!=expected:raise ValueError('Context evidence differs from its full transcript')
            if (data.get('method')!='unprompted-full-episode-vad-v1' or data.get('decoding',{}).get('vad_filter') is not True
                    or digest(whole)!=data['whole_episode_sha256']
                    or any(baseline['input'][key]!=data[key] for key in ('cue','model','source_audio_sha256','clip_sha256','model_files'))):
                raise ValueError('Whole-episode evidence provenance mismatch')
            inputs[str(baseline_path)]=digest(baseline_path);inputs[str(whole)]=digest(whole)
            if (data['cue']!=row or data['model']!=model or data['source_audio_sha256']!=source_sha
                    or digest(clip)!=data['clip_sha256']):raise ValueError('Original-audio evidence does not match this cue')
            inputs[str(path)]=digest(path);inputs[str(clip)]=digest(clip)
            records[model]={'segments':record['segments'],'baseline_segments':baseline['segments'],'model_files_sha256':data['model_files'],
                            'evidence_sha256':inputs[str(path)],'human_listened':False}
        result[row['id']]={'cue':row,'models':records,'source_speaker_verified':False}
    if required!=set(result):raise ValueError('Missing disputed-cue audio evidence')
    return result,inputs


def validate_source_readings(review,rows,evidence):
    originals={r['id']:r for r in rows};readings={}
    for cue in review['cues']:
        if cue['id'] not in evidence:
            if cue.get('source_reading_status')!='not_requested' or cue.get('source_audio_reading'):
                raise ValueError('Unsupported source reading without audio evidence')
            continue
        reading=cue.get('source_audio_reading','');status=cue.get('source_reading_status')
        if status not in ('subtitle_confirmed','transcription_corrected') or not reading.strip() or not cue.get('source_reading_evidence'):
            raise ValueError('Unresolved source reading; no synthesis')
        tokens=reading_tokens(reading);row=originals[cue['id']]
        if not tokens:raise ValueError('Empty original-audio reading')
        if status=='subtitle_confirmed' and tokens!=reading_tokens(row['text']):raise ValueError('Subtitle confirmation changed words')
        models=evidence[cue['id']]['models']
        if set(models)!={'small.en','medium.en'}:raise ValueError('Two designated ASR models required')
        for model in models.values():
            # VAD/context must never silently lose a confidently heard negation,
            # modality or number from the independently preserved raw clip.
            critical={'not','no','never','cannot','can','could','would','should','must','will','shall',
                      'zero','one','two','three','four','five','six','seven','eight','nine','ten',
                      'eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty'}
            from collections import Counter
            protected=Counter(t for segment in model.get('baseline_segments',[]) for w in segment.get('words',[])
                if w['probability']>=.5 and row['start']-.1<=(w['start']+w['end'])/2<=row['end']+.1
                for t in reading_tokens(w['word']) if t in critical or t.isdigit())
            if protected-Counter(tokens):raise ValueError('Context ASR omitted a protected raw-cue word')
            words=[w for segment in model['segments'] for w in segment.get('words',[])]
            previous=-math.inf
            for w in words:
                if not (math.isfinite(w['start']) and math.isfinite(w['end']) and
                        previous<=w['start']<=w['end'] and 0<=w['probability']<=1):
                    raise ValueError('Invalid ASR word timing or confidence')
                previous=w['end']
            # Edge padding can contain adjacent dialogue. Every word whose
            # midpoint belongs to the original cue MUST be covered, including
            # low-confidence words (which block rather than silently disappear).
            core=[i for i,w in enumerate(words) if row['start']<=(w['start']+w['end'])/2<=row['end']]
            if not core:raise ValueError('No core-cue words support the reading')
            threshold=.65 if status=='transcription_corrected' else .5
            supported=False
            for first in range(core[0]+1):
                for last in range(core[-1],len(words)):
                    covered=words[first:last+1]
                    if any(w['start']<row['start']-.35 or w['end']>row['end']+.35 or
                           w['probability']<.35 for w in covered):continue
                    heard=[t for w in covered for t in reading_tokens(w['word'])]
                    if heard!=tokens:continue
                    # Do not clip a negation, number or modal from a cue edge.
                    omitted=words[:first]+words[last+1:]
                    critical={'not','no','never','cannot','can','could','would','should','must','will','shall',
                              'zero','one','two','three','four','five','six','seven','eight','nine','ten',
                              'eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty'}
                    if any(w['end']>=row['start']-.35 and w['start']<=row['end']+.35 and
                           any(t in critical or t.isdigit() for t in reading_tokens(w['word'])) for w in omitted):continue
                    if sum(w['probability'] for w in covered)/len(covered)>=threshold:supported=True
            if not supported:
                raise ValueError('Source reading must cover all core words in both models inside the original cue')
        readings[cue['id']]={'original_subtitle_text':row['text'],'corroborated_audio_reading':reading,
            'status':status,'evidence':cue['source_reading_evidence'],'human_listened':False}
    return readings


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
    max_gap={9:.85,15:1.0}.get(n,.6) if getattr(args,'finalize_pending',False) else .6
    if getattr(args,'finalize_pending',False) and n in (21,22):
        # Fix a known excerpt/episode association error using the user's mapped
        # final storyboard. Original English timed source and reader evidence stay intact.
        context=copy.deepcopy(context)
        refs=storyboard_reference(n,storyboard.read_text(encoding='utf-8-sig'))
        context['episodes'][str(n)]['script_excerpt']='\n\n'.join(e['script'] for e in refs['entries'])
        context['mapped_excerpt_revision']={'old_context_sha256':inputs[str(context_path)],
            'reference_sha256':inputs[str(storyboard)],'reference_entries':[e['storyboard_episode'] for e in refs['entries']],
            'reason':'Old script_excerpt used the previous storyboard episode; mapped dialogue reference corrected.'}
        if not any(s['sha256']==inputs[str(storyboard)] for s in context['sources']):
            context['sources'].append({'filename':storyboard.name,'sha256':inputs[str(storyboard)],
                                       'version':'user-supplied final storyboard; dialogue-mapped 2026-10-17'})
    audio_evidence={}
    if getattr(args,'source_evidence',False):
        audio_evidence,extra=source_audio_evidence(n,rows,Path(plan['assets']['source_audio']),args.prior_root)
        inputs.update(extra)
        if n==20 and 'e20-8' in audio_evidence:
            # The final storyboard labels this voiceover Laura; the prior
            # Carmilla assignment was provisional, not an audio-verified identity.
            if old['e20-8']['cue_ids']!=['e20-8'] or annotations['e20-8']['speaker']!='unknown':
                raise ValueError('Unexpected source reader scope; review before changing provisional casting')
            old=copy.deepcopy(old);old['e20-8']['production_voice']='Laura'
    bible=read_json(bible_path);glossary=validate_bible(bible)
    payload={'episode':n,'locked_bible':bible,'reviewed_screenplay_context':context,
             'user_storyboard_sha256':inputs[str(storyboard)],
             'user_storyboard_reference':storyboard_reference(n,storyboard.read_text(encoding='utf-8-sig')),'timed_source':rows,
             'previous_episode_revisions':preceding[-2:],
             'old_translation_reference':[{'cue_ids':u['cue_ids'],'text':u['translation']} for u in plan['units']],
             'production_voice_per_cue':{c:u['production_voice'] for c,u in old.items()},
             'known_issue':'EP29 e29-8 source How many years. conflicts with screenplay minions; retain original text and flag for original-audio verification, never silently replace it.'}
    payload['grouping_max_gap_seconds']=max_gap
    if audio_evidence:payload['source_audio_evidence']=audio_evidence
    if n==20 and 'e20-8' in audio_evidence:payload['provisional_casting_revision']='e20-8 uses Laura per user final storyboard voiceover; source evidence reader remains unknown, NOT audio-verified.'
    if getattr(args,'prior_root',None):
        payload['revision_feedback']=revision_feedback(n,args,preceding)
        payload['previous_episode_revisions']=payload['revision_feedback'].pop('previous_episode_revisions')
        inputs.update(payload['revision_feedback']['source_sha256'])
    bind(folder/'editorial-input.json',{'sha256':inputs,'context':payload,'policy_version':1})
    schema=folder/'schema.json';save_json(schema,response_schema(bool(audio_evidence)))
    prompt=('Revise this entire episode into natural spoken Brazilian Portuguese with screenplay context. '
            'Preserve meaning, names, negation, relationship, deadlines and original cue IDs/order/times. '
            'Do not invent dialogue from the screenplay or silently fix uncertain ASR. Keep unknown evidence readers unknown. '
            'The user storyboard is reference only and has 33 entries for 32 videos: do not assume episode numbers align. '
            'Keep correct existing wording where suitable; improve awkward language or overly long phrasing faithfully. '
            'Translate complete thoughts, distribute wording across their original cues, and propose adjacent same-speaker '
            f'groups for natural delivery; groups cover ALL cues once, including singleton groups. Gap <={max_gap}s. '
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
            'Inspect revision_feedback.regroup_candidates for overlong short fragments: adjacent same-speaker '
            'clauses may be delivered together when semantically natural; validate every original grouping constraint. '
            'For a measured group still overlong, aim comfortably below its maximum (about 80 percent where faithful), '
            'using idiomatic equivalent phrasing rather than deleting meaning, names or negation. '
            'When original source_audio_evidence is supplied, quote the actual English source_audio_reading for each '
            'disputed cue, supported by BOTH timestamped ASR models. Do not import words from outside its cue window. '
            'Use subtitle_confirmed for the original wording, transcription_corrected for a corroborated different reading, '
            'and uncertain if the evidence disagrees or is unclear. Translate the corroborated spoken reading while '
            'retaining the original subtitle text/times as provenance. Other cues use not_requested with an empty reading. '
            'A current-cut reading corroborated by both ASR models takes priority over an older script: retain the '
            'documentary difference as a warning; unresolved speech meaning remains an error. ASR is not human listening '
            'or speaker identification. Never claim source_speaker_verified or native pronunciation approval. '
            'Consult the supplied inline context and mapped storyboard references. Do not call MCP, clone/TTS/upload, edit files, '
            'change source/casting or credentials. Return only structured data.\n'+__import__('json').dumps(payload,ensure_ascii=False))
    draft_path=folder/'draft.json'
    draft=read_json(draft_path) if draft_path.exists() else call_codex(args.codex_exe,prompt,schema,draft_path,folder/'draft.private.log')
    # Validate structural/casting constraints after review, allowing draft defects to be repaired.
    reviewed_path=folder/'reviewed.json'
    reviewed=read_json(reviewed_path) if reviewed_path.exists() else call_codex(args.codex_exe,
        prompt+'\nPerform a second semantic and continuity review, correct the candidate, verify all grouping constraints.\n'+
        __import__('json').dumps(draft,ensure_ascii=False),schema,reviewed_path,folder/'review.private.log')
    readings=validate_source_readings(reviewed,rows,audio_evidence) if audio_evidence else {}
    validate_editorial(reviewed,rows,old,annotations,glossary,max_gap)
    if any(digest(Path(p))!=sha for p,sha in inputs.items()): raise ValueError('Editorial inputs changed')
    revised_context=copy.deepcopy(context)
    revised_context['revision_basis']={'original_context_sha256':inputs[str(context_path)],'policy':'EP02-feedback full-season rerun; no native listening approval'}
    if readings:revised_context['corroborated_source_audio_readings']=readings
    if n==20 and 'e20-8' in readings:
        revised_context['provisional_production_casting']={'e20-8':{'prior':'Carmilla','revised':'Laura',
            'reference':'final.html mapped EP-21 voiceover Laura','reference_sha256':inputs[str(storyboard)],
            'evidence_type':'screenplay_not_audio','source_speaker_verified':False}}
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
                      'source_audio_readings':{c:readings[c] for c in group if c in readings},
                      'issues':[issue for c in cs for issue in c['issues']]})
    new_plan={'episode':n,'project_id':59,'assets':plan['assets'],'units':units,'input_sha256':inputs,
              'reviewed_context_sha256':digest(folder/'screenplay-context.json'),
              'reviewed_response_sha256':digest(reviewed_path),'translation_srt_sha256':digest(folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt'),
              'blocking_issues':['Original audio verification required for e29-8 before complete new episode release'] if n==29 and 'e29-8' not in readings else []}
    bind(folder/'reviewed-plan-fingerprint.json',new_plan)
    save_json(folder/'plan.json',new_plan)
    return {'episode':n,'cues':reviewed['cues'],'consistency_notes':reviewed['consistency_notes']}


def revision_feedback(n,args,preceding=()):
    prior=Path(args.prior_root)
    if prior.resolve() not in {BASE_ROOT.resolve(),RETRY_ROOT.resolve(),FINAL_ROOT.resolve(),TIMING_ROOT.resolve()}:raise ValueError('Only existing season attempts may seed this retry')
    folder=prior/f'episode-{n:02}'
    continuity={int(row['episode']):row for row in preceding[-2:]}
    data={'source_root':str(prior),'source_sha256':{},'prior_editorial':None,'measured_groups':[]}
    for previous in range(max(1,n-2),n):
        if previous in continuity:continue
        ep=next((root/f'episode-{previous:02}' for root in ((prior,FINAL_ROOT,RETRY_ROOT,BASE_ROOT) if prior.resolve()==TIMING_ROOT.resolve() else (prior,BASE_ROOT))
                 if (root/f'episode-{previous:02}'/'render-report.json').exists()),None)
        if ep is None:continue
        p=read_json(ep/'plan.json');validate_reviewed_plan(ep,p)
        if digest(ep/'reviewed.json')!=p['reviewed_response_sha256']:
            raise ValueError('Prior completed episode editorial changed')
        reviewed=read_json(ep/'reviewed.json')
        continuity[previous]={'episode':previous,'cues':reviewed['cues'],'consistency_notes':reviewed['consistency_notes'],
                              'native_listening_approved':False}
        for name in ('plan.json','reviewed.json','render-report.json'):
            data['source_sha256'][str(ep/name)]=digest(ep/name)
    data['previous_episode_revisions']=[continuity[k] for k in sorted(continuity)[-2:]]
    for name in ('reviewed.json','plan.json','duration-measurements.json'):
        p=folder/name
        if p.exists():data['source_sha256'][str(p)]=digest(p)
    if (folder/'reviewed.json').exists():data['prior_editorial']=read_json(folder/'reviewed.json')
    if not (folder/'plan.json').exists():return data
    plan=read_json(folder/'plan.json');validate_reviewed_plan(folder,plan)
    duration=float(probe(Path(plan['assets']['video']),args.ffmpeg)['format']['duration'])
    for i,u in enumerate(plan['units']):
        wav=folder/'utterances'/u['id']/'original.wav'
        if not wav.exists() and prior.resolve() in {RETRY_ROOT.resolve(),FINAL_ROOT.resolve(),TIMING_ROOT.resolve()}:
            cartesia=read_json('output/drama-01/cartesia-pilot-voices/voice-bank.json')
            minimax=read_json('output/drama-01/voice-bank.json')['voices']
            req,_=request(u,cartesia,minimax)
            for cache in ([FINAL_ROOT,RETRY_ROOT,BASE_ROOT] if prior.resolve()==TIMING_ROOT.resolve() else
                          [RETRY_ROOT,BASE_ROOT] if prior.resolve()==FINAL_ROOT.resolve() else [BASE_ROOT]):
                candidate=paid_audio_folder(n,req,wav.parent,cache)/'original.wav'
                if candidate.exists():wav=candidate;break
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
    max_gap={9:.85,15:1.0}.get(n,.6) if getattr(args,'finalize_pending',False) else .6
    data['regroup_candidates']=[]
    for index,(a,b) in enumerate(zip(plan['units'],plan['units'][1:])):
        if (a.get('source_speaker') in (None,'unknown') or a.get('source_speaker')!=b.get('source_speaker')
            or a.get('production_voice')!=b.get('production_voice') or a.get('emotion')!=b.get('emotion')
            or not 0<=b['start']-a['end']<=max_gap+1e-9):continue
        following=plan['units'][index+2]['start'] if index+2<len(plan['units']) else duration
        end=max(b['end'],min(duration,following-.1,b['end']+.8))
        data['regroup_candidates'].append({'cue_ids':a['cue_ids']+b['cue_ids'],
            'maximum_seconds':(end-a['start'])*1.2,'requires_semantic_review':True,
            'reason':'Same evidence speaker, production voice and emotion; review as one complete thought if timing is tight.'})
    if any(digest(Path(p))!=sha for p,sha in data['source_sha256'].items()):
        raise ValueError('Prior revision changed while collecting feedback')
    return data


def paid_audio_folder(n,req,target,prior_root=None):
    """Reuse the exact prior request, including ambiguous receipts; never route around them."""
    if prior_root is None:return target
    prior=Path(prior_root)
    if prior.resolve() not in {BASE_ROOT.resolve(),RETRY_ROOT.resolve(),FINAL_ROOT.resolve(),TIMING_ROOT.resolve()}:raise ValueError('Unexpected paid cache root')
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


def speech_window(natural,target,start,previous_end,allow_preroll=False):
    audio_start=start
    if natural/target>1.2 and allow_preroll:
        available=min(.08,max(0,start-max(0,previous_end+.1)))
        lead=min(available,max(0,natural/1.2-target)+.05)
        audio_start-=lead;target+=lead
    return audio_start,target,max(1.,natural/target)


def fit_speech(trimmed,fitted,target,factor,ffmpeg):
    if not 1<=factor<=1.2:raise ValueError('Unapproved speech speed')
    for attempt in range(4):
        run([ffmpeg,'-v','error','-y','-i',trimmed,'-af',f'atempo={factor:.8f}',
             '-ar',str(RATE),'-ac','1','-c:a','pcm_s16le',fitted])
        audio=read_audio(fitted,ffmpeg)
        if len(audio)<=math.floor(target*RATE):return audio,factor
        if factor==1.2:break
        # Codec frame padding must not make the heuristic jump beyond the
        # approved cap without testing that cap. No truncation or new TTS.
        factor=1.2 if attempt>=2 else min(1.2,factor*len(audio)/(target*RATE)*1.005)
    raise ValueError('Cannot fit without truncating/over-speeding')


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
    render_input={'plan':plan,'asset_hashes':asset_hashes,'requests':requests,
          'cartesia_bank_sha256':digest(cartesia_path),'minimax_bank_sha256':digest(minimax_path),
          'max_atempo':1.2,'max_post_subtitle_gap_seconds':.8,'cloning_enabled':False}
    if getattr(args,'finalize_pending',False):render_input['max_pre_subtitle_gap_seconds']=.08
    bind(folder/'render-input.json',render_input)
    cache_roots=getattr(args,'cache_roots',None) or ([args.prior_root] if getattr(args,'prior_root',None) else [])
    # Preflight all prior attempts, including requests whose wording changed.
    for prior in cache_roots:paid_audio_folder(n,{},folder/'unused-cache-probe',prior)
    client=Mflix(args.mcp_config);results=[];measurements=[]
    for index,(unit,(req,provider)) in enumerate(zip(plan['units'],requests)):
        target_dir=folder/'utterances'/unit['id']
        cached=target_dir
        for prior in cache_roots:
            found=paid_audio_folder(n,req,target_dir,prior)
            if found!=target_dir:
                cached=found;break
        path,receipt=generate(client,req,cached)
        target_dir.mkdir(parents=True,exist_ok=True)
        samples,_,_=trim_edges(read_audio(path,args.ffmpeg));natural=len(samples)/RATE
        next_start=plan['units'][index+1]['start'] if index+1<len(plan['units']) else duration
        limit=min(duration,next_start-.1,unit['end']+.8)
        if limit<unit['end']-.001: limit=unit['end']
        target=max(unit['end'],min(limit,unit['start']+natural))-unit['start']
        if getattr(args,'measure_only',False):
            maximum=(max(unit['end'],limit)-unit['start'])*1.2
            measurements.append({'cue_ids':unit['cue_ids'],'natural_seconds':natural,
                'maximum_seconds':maximum,'requires_shortening':natural>maximum,
                'audio_sha256':digest(path),'receipt_sha256':digest(cached/'audio-receipt.json')})
            save_json(folder/'duration-measurements.json',{'plan_sha256':digest(folder/'plan.json'),
                'complete':len(measurements)==len(requests),'groups':measurements,'native_listening_passed':False})
            print('DURATION_MEASURED',n,len(measurements),len(requests),flush=True)
            continue
        previous_end=results[-1]['audio_start']+results[-1]['fitted_duration_seconds'] if results else -.1
        audio_start,target,factor=speech_window(natural,target,unit['start'],previous_end,getattr(args,'finalize_pending',False))
        if factor>1.2: raise ValueError('Measured speech too long: revise faithfully; no automatic paid speed retries')
        trimmed,fitted=target_dir/'trimmed.wav',target_dir/'fitted.wav';write_audio(trimmed,samples)
        audio,factor=fit_speech(trimmed,fitted,target,factor,args.ffmpeg)
        results.append({**unit,'provider':provider,'task_id':receipt['task_id'],'request':req,'atempo_factor':factor,
                        'paid_audio_reused_from_prior_attempt':cached!=target_dir,
                        'audio_start':audio_start,'pre_subtitle_gap_used_seconds':unit['start']-audio_start,
                        'natural_duration_seconds':natural,'fitted_duration_seconds':len(audio)/RATE,
                        'post_subtitle_gap_used_seconds':max(0,audio_start+len(audio)/RATE-unit['end']),
                        'fitted_path':str(fitted),'fitted_sha256':digest(fitted),'native_listening_passed':False})
        save_json(folder/'progress.json',{'episode':n,'stage':'synthesizing','complete':len(results),'total':len(requests),'updated_at':time.time()})
    if getattr(args,'measure_only',False):return
    import numpy as np
    dialogue=np.zeros(math.ceil(duration*RATE),dtype=np.float32)
    for r in results:
        audio=read_audio(Path(r['fitted_path']),args.ffmpeg);start=round(r['audio_start']*RATE)
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
    p.add_argument('--finalize-pending',action='store_true',help='Use latest measured attempt, mapped excerpts, and both paid caches')
    p.add_argument('--episodes',nargs='+',type=int,help='Explicit subset of pending episodes; never rerun completed candidates')
    p.add_argument('--source-evidence',action='store_true',help='Require two timestamped original-audio ASR records for disputed cues')
    p.add_argument('--wait-for-production-lock',type=int,default=0)
    a=p.parse_args()
    if sys.platform!='win32':p.error('All business execution remains on Windows')
    if a.stage in ('editorial','all') and (not a.codex_exe or not a.codex_exe.is_file()):p.error('Existing native Codex executable required')
    if a.stage in ('render','all') and (not a.mcp_config or not a.ffmpeg or not a.ffmpeg.is_file()):p.error('Production config/ffmpeg required')
    if a.retry_pending and a.finalize_pending:p.error('Choose one revision stage')
    if a.episodes and not (a.retry_pending or a.finalize_pending):p.error('Episode subsets require an isolated revision stage')
    if a.source_evidence and not a.finalize_pending:p.error('Source evidence requires an isolated final revision')
    if not 0<=a.wait_for_production_lock<=14400:p.error('Production lock wait must be 0..14400 seconds')
    episodes=list(range(1,33));a.prior_root=None;a.cache_roots=[]
    if a.retry_pending or a.finalize_pending:
        if not a.ffmpeg or not a.ffmpeg.is_file():p.error('Measured retry needs FFmpeg')
        a.prior_root=BASE_ROOT;ROOT=RETRY_ROOT
        if a.finalize_pending:a.prior_root=RETRY_ROOT;ROOT=FINAL_ROOT
        a.cache_roots=[a.prior_root]+([BASE_ROOT] if a.finalize_pending else [])
    ROOT.mkdir(parents=True,exist_ok=True)
    # Share the original season lock so an old runner cannot submit in parallel.
    with process_lock(BASE_ROOT/'season.lock',timeout=a.wait_for_production_lock):
        previous_state=read_json(ROOT/'season-progress.json') if (ROOT/'season-progress.json').exists() else {'episodes':{}}
        if a.retry_pending or a.finalize_pending:
            baseline=read_json(BASE_ROOT/'season-progress.json')
            if set(baseline['episodes'])!={str(i) for i in range(1,33)}:p.error('Incomplete prior season status')
            if a.finalize_pending:baseline['episodes'].update(read_json(RETRY_ROOT/'season-progress.json')['episodes'])
            baseline['episodes'].update(previous_state['episodes'])
            episodes=[n for n in episodes if baseline['episodes'][str(n)]['stage']!='rendered_candidate']
            if a.episodes:
                if len(set(a.episodes))!=len(a.episodes) or not set(a.episodes).issubset(episodes):
                    p.error('Explicit episodes must be unique pending episodes')
                episodes=[n for n in episodes if n in a.episodes]
            if not episodes:p.error('No pending episodes to retry')
        state={'authorized_scope':'Carmilla 32 episode rerun using existing EP02 feedback; no waiting for diagnostic reviews',
               'selected_episodes':episodes,'native_acceptance_passed':False,
               'episodes':dict(previous_state['episodes']) if a.retry_pending or a.finalize_pending else {}};preceding=[]
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
        complete='editorial_complete' if a.stage=='editorial' else ('selected_candidates_complete' if a.retry_pending or a.finalize_pending else 'complete_candidates')
        state['stage']=complete if all(e['stage']==expected for e in state['episodes'].values()) else 'requires_review'
        save_json(ROOT/'season-progress.json',state)
        if state['stage']=='requires_review':raise SystemExit(2)


if __name__=='__main__':main()
