"""Append only separately reviewed, selected-cut ASR dialogue with literal screenplay evidence."""
import copy
import math
from pathlib import Path
import re

from dub_episode import digest
from translate import read_json,fingerprint


def norm(value):return ' '.join(re.findall(r'\w+',value.casefold()))


def checked_words(report,indices,source_text,start,end,frozen_window=None):
    words=[w for s in report['segments'] for w in s.get('words',[])]
    if (not indices or len(indices)>80 or any(type(i) is not int for i in indices)
            or indices!=list(range(indices[0],indices[0]+len(indices)))
            or indices[0]<0 or indices[-1]>=len(words)):
        raise ValueError('One contiguous actual source-word span required')
    selected=[words[i] for i in indices]
    previous=0.
    for word in selected:
        times=(word['start'],word['end'])
        if (any(type(t) not in (int,float) or not math.isfinite(t) for t in times)
                or not 0<=word['start']<=word['end'] or word['start']<previous-.001):
            raise ValueError('Actual source word times must be finite, valid, and ordered')
        previous=word['end']
    if (norm(' '.join(w['word'] for w in selected))!=norm(source_text)
            or start>min(w['start'] for w in selected)+.001
            or end<max(w['end'] for w in selected)-.001):
        raise ValueError('Additional source phrase or window differs from actual cut words')
    if frozen_window is not None:
        actual=(min(w['start'] for w in selected),max(w['end'] for w in selected))
        if (len(frozen_window)!=2 or any(abs(a-b)>.001 for a,b in zip(actual,frozen_window))
                or any(abs(a-b)>.001 for a,b in zip((start,end),frozen_window))):
            raise ValueError('Actual phrase location differs from the independently frozen source window')
    return selected


def apply(rows,candidate,context,decision,media,inputs):
    path=decision.get('production_source_additions_path')
    if not path:return rows,candidate
    path=Path(path);manifest=read_json(path)
    if (decision['project_id']!=100 or decision['episode'] not in (8,9)
            or manifest['project_id']!=100 or manifest['episode']!=decision['episode']
            or manifest.get('derived_source_context_reviewed') is not True
            or manifest['source_input_sha256']!=decision['source_input_sha256']
            or manifest['baseline_result_sha256']!=decision['baseline_result_sha256']
            or manifest['video_sha256']!=media['source']['video_sha256']
            or manifest['timeline_sha256']!=digest(decision['production_time_map_path'])
            or manifest['screenplay_context_fingerprint']!=fingerprint(context['scripts'])
            or manifest.get('native_listening_passed') is not False):
        raise ValueError('Separate reviewed derived-source screenplay/cut context required')
    if not manifest['inputs_sha256']:raise ValueError('Physical source and translation evidence required')
    required={manifest['translation_review_path'],manifest['audit_report_path'],manifest['source_candidate_path']}
    if not required<=set(manifest['inputs_sha256']):raise ValueError('Source and independent translation audit must be frozen')
    for p,sha in manifest['inputs_sha256'].items():
        if digest(p)!=sha:raise ValueError('Derived source or independent text review changed')
        inputs[p]=sha
    review=read_json(manifest['translation_review_path'])
    if (review['project_id']!=100 or review['verdict']!='independent_semantic_role_mode_direction_candidate_pass_with_single_trailing_word_correction'):
        raise ValueError('Expected independent semantic review missing')
    frozen_source_hashes=[sha for p,sha in review['input_sha256'].items()
                          if Path(p).name==Path(manifest['source_candidate_path']).name]
    if frozen_source_hashes!=[digest(manifest['source_candidate_path'])]:
        raise ValueError('Independent translation review is bound to another source-candidate version')
    approved={x['id']:x for x in review['new_records'] if x['episode']==decision['episode']}
    source_proposals=read_json(manifest['source_candidate_path'])['phrases']
    by_proposal={x['proposal_id']:x for x in source_proposals}
    items=manifest['cues']
    if (not 1<=len(items)<=5 or len({x['proposal_id'] for x in items})!=len(items)
            or len(approved)!=sum(x['episode']==decision['episode'] for x in review['new_records'])
            or len(by_proposal)!=len(source_proposals) or {x['proposal_id'] for x in items}!=set(approved)):
        raise ValueError('Only the full reviewed source-addition scope may be appended')
    from prepare_review_episode_editorial import validate_schema,schema
    spec=schema()['properties']['cues']['items']
    scripts={s['asset_id']:s['text'] for s in context['scripts']}
    roles={r['stable_id'] for r in context['series_context']['characters']}|{'unknown'}
    rows=copy.deepcopy(rows);candidate=copy.deepcopy(candidate);old_ids=[r['id'] for r in rows];ids=set(old_ids)
    for item in items:
        original=by_proposal[item['proposal_id']];frozen=approved[item['proposal_id']]
        source=item['source'];cue=item['candidate'];asr_path=item['asr_report_path']
        if (asr_path not in manifest['inputs_sha256']
                or manifest['inputs_sha256'][asr_path]!=frozen['source_transcript_sha256']
                or frozen['selected_video_sha256']!=media['source']['video_sha256']
                or original['video_sha256']!=media['source']['video_sha256']):
            raise ValueError('Actual selected-cut transcript evidence is not bound')
        if (original['source_phrase_candidate']!=frozen['source_phrase_candidate']
                or original['new_picture_word_window']!=frozen['source_word_window']
                or original['source_transcript_sha256']!=frozen['source_transcript_sha256']):
            raise ValueError('Same-ID source proposal differs from the frozen independent review')
        report=read_json(asr_path)
        if report['reference_sha256'] not in media['output_sha256'].values():
            raise ValueError('Transcript is from another audio version')
        if (source['id'] in ids or cue['id']!=source['id']
                or not re.fullmatch(fr'e{decision["episode"]:02d}-[0-9]+',source['id'])
                or str(source['episode'])!=str(decision['episode'])
                or source.get('is_original_supplied_srt_cue') is not False
                or source.get('source_kind')!='derived_selected_video_ASR_and_matched_screenplay'):
            raise ValueError('New machine source must not overwrite or impersonate original subtitles')
        selected=checked_words(report,item['word_indices'],source['text'],source['start'],source['end'],frozen['source_word_window'])
        if (norm(' '.join(w['word'] for w in selected))!=norm(frozen['raw_asr_text'])
                or cue['translation']!=frozen['translation']
                or cue['script_asset_id']!=frozen['script_asset_id']
                or cue['script_quote']!=frozen['literal_script_quote']
                or cue['script_role']!=frozen['production_role_candidate']):
            raise ValueError('Source, wording, or casting differs from independent review')
        validate_schema(cue,spec)
        if (not cue['translation'].strip() or '\r' in cue['translation'] or '\x00' in cue['translation']
                or re.search(r'\n\s*\n',cue['translation']) or cue['script_role'] not in roles
                or cue['script_asset_id'] not in scripts or cue['script_quote'] not in scripts[cue['script_asset_id']]):
            raise ValueError('Invalid subtitle or unbound literal screenplay role/quote')
        unit=next((u for u in decision['units'] if u['cue_id']==source['id']),None)
        language='Italian' if frozen['text_language']=='it' else 'Portuguese'
        if (unit is None or sum(u['cue_id']==source['id'] for u in decision['units'])!=1
                or unit['role']!=frozen['production_role_candidate']
                or unit['delivery_mode']!=frozen['delivery_mode']
                or unit['emotion']!=frozen['emotion_intent_candidate']
                or unit.get('language_boost','Portuguese')!=language):
            raise ValueError('Production unit changed reviewed role, mode, acting direction, or foreign-language intent')
        ids.add(source['id']);rows.append(source);candidate['cues'].append(cue)
    rows.sort(key=lambda r:r['start']);by_id={c['id']:c for c in candidate['cues']}
    if [r['id'] for r in rows if r['id'] in set(old_ids)]!=old_ids:raise ValueError('Original cue order changed')
    candidate['cues']=[by_id[r['id']] for r in rows]
    from pipeline_timeline import apply_mapping
    apply_mapping(rows,[dict(id=r['id'],source_start=r['start'],source_end=r['end'],source_text=r['text'],
                  start=r['start'],end=r['end'],evidence='Reviewed complete derived source') for r in rows],media['video_seconds'])
    inputs[str(path)]=digest(path)
    return rows,candidate
