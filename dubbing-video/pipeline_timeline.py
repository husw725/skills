"""Apply reviewed cut-specific cue times, retaining original subtitle and screenplay evidence."""
import copy
import math
from pathlib import Path
import re

from dub_episode import digest
from translate import read_json, fingerprint


def apply_mapping(rows, mapping, duration):
    if len(mapping) != len(rows) or [x['id'] for x in mapping] != [r['id'] for r in rows]:
        raise ValueError('Every original cue requires one ordered explicit time mapping')
    result = []
    previous = 0
    for source, item in zip(rows, mapping):
        if (item['source_start'] != source['start'] or item['source_end'] != source['end']
                or item['source_text'] != source['text'] or not item['evidence'].strip()):
            raise ValueError('Time mapping must retain exact original subtitle evidence')
        start, end = item['start'], item['end']
        if (any(type(t) not in (int, float) or not math.isfinite(t)
                or abs(t*1000-round(t*1000)) > 1e-6 for t in (start, end))
                or not 0 <= start < end <= duration+.001 or start < previous-.001):
            raise ValueError('Mapped source windows must be finite, ordered, nonoverlapping milliseconds in the cut')
        result.append({**source, 'start': start, 'end': end})
        previous = end
    return result


def apply(rows, candidate, context, decision, media, inputs):
    path = decision.get('production_time_map_path')
    if not path:
        return rows, candidate
    path = Path(path); timeline = read_json(path)
    reviewed_path = Path(timeline['reviewed_context_path']); reviewed = read_json(reviewed_path)
    if (decision['project_id'] != 100 or decision['episode'] not in (6, 8, 9)
            or timeline['project_id'] != 100 or timeline['episode'] != decision['episode']
            or timeline['source_input_sha256'] != decision['source_input_sha256']
            or timeline['baseline_result_sha256'] != decision['baseline_result_sha256']
            or timeline['video_sha256'] != media['source']['video_sha256']
            or timeline['media_receipt_sha256'] != digest(decision['media_receipt_path'])
            or digest(reviewed_path) != timeline['reviewed_context_sha256']
            or reviewed.get('production_timeline_candidate_approved') is not True
            or reviewed.get('original_actor_identity_verified') is not False
            or reviewed.get('native_listening_passed') is not False
            or reviewed['source_input_sha256'] != timeline['source_input_sha256']
            or reviewed['baseline_result_sha256'] != timeline['baseline_result_sha256']
            or reviewed['video_sha256'] != timeline['video_sha256']
            or reviewed['mapping_fingerprint'] != fingerprint(timeline['cues'])
            or reviewed['screenplay_context_fingerprint'] != fingerprint(context['scripts'])):
        raise ValueError('Reviewed screenplay/source/cut-specific timeline binding required')
    if not reviewed['inputs_sha256']:
        raise ValueError('Physical acoustic evidence must be hash-bound')
    acoustic_path = reviewed['acoustic_evidence_path']
    if reviewed['inputs_sha256'].get(acoustic_path) != reviewed['acoustic_evidence_sha256']:
        raise ValueError('Acoustic proof must appear in reviewed input bindings')
    acoustic = read_json(acoustic_path)
    if (digest(acoustic_path) != reviewed['acoustic_evidence_sha256']
            or acoustic.get('approved') is not True or acoustic.get('project_id') != 100
            or acoustic.get('episode') != decision['episode']):
        raise ValueError('Actual approved acoustic cue proof required')
    bindings = acoustic['source_bindings']
    if (bindings['selected_picture']['video_sha256'] != media['source']['video_sha256']
            or bindings['source_input']['sha256'] != decision['source_input_sha256']
            or bindings['editorial_result']['sha256'] != decision['baseline_result_sha256']
            or bindings['media_manifest']['sha256'] != digest(decision['media_receipt_path'])
            or bindings['selected_dialogue']['sha256'] not in media['output_sha256'].values()):
        raise ValueError('Acoustic proof refers to a different source or picture cut')
    physical = {**bindings['declared_physical_inputs_sha256']}
    for name in ('source_input', 'editorial_result', 'original_candidate_srt', 'media_manifest',
                 'selected_dialogue', 'selected_background', 'original_dialogue', 'waveform_proof'):
        item = bindings[name]; physical[item['path']] = item['sha256']
    physical[bindings['selected_picture']['video']] = bindings['selected_picture']['video_sha256']
    if any(reviewed['inputs_sha256'].get(p) != sha for p, sha in physical.items()):
        raise ValueError('Every physical acoustic and screenplay source must be hash-bound')
    proof = acoustic['cues']
    if len(proof) != len(rows):
        raise ValueError('Complete acoustic proof for original cue scope required')
    for source, mapped_cue, proved in zip(rows, timeline['cues'], proof):
        if (proved['id'] != source['id'] or proved['text'] != source['text']
                or proved['original_start'] != source['start'] or proved['original_end'] != source['end']
                or round(proved['start'], 3) != mapped_cue['start']
                or round(proved['end'], 3) != mapped_cue['end']):
            raise ValueError('Mapped cue differs from independent physical source proof')
    for p, sha in reviewed['inputs_sha256'].items():
        if digest(p) != sha: raise ValueError('Timeline acoustic or screenplay review evidence changed')
        inputs[p] = sha
    mapped = apply_mapping(rows, timeline['cues'], media['video_seconds'])
    inputs[str(path)] = digest(path); inputs[str(reviewed_path)] = digest(reviewed_path)
    audit = Path(reviewed['audit_report_path'])
    if digest(audit) != reviewed['audit_report_sha256']: raise ValueError('Timeline review report changed')
    inputs[str(audit)] = digest(audit)
    # Source additions require a separate source-and-translation review path.
    # This adapter deliberately covers only already approved original cues.
    if timeline.get('additional_cues'):
        raise ValueError('Additional dialogue is not approved by a time-only mapping')
    return mapped, candidate


def subtitle(rows, candidate):
    from prepare_review_episode_editorial import srt_time
    if [r['id'] for r in rows] != [c['id'] for c in candidate['cues']]:
        raise ValueError('Derived subtitle cue order changed')
    return '\n\n'.join(f'{r["id"].split("-",1)[1]}\n{srt_time(r["start"])} --> {srt_time(r["end"])}\n{c["translation"]}'
                       for r, c in zip(rows, candidate['cues']))+'\n'
