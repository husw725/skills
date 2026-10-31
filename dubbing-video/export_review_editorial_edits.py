"""Export independently reviewed, source-bound text edits without changing model receipts."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import prepare_review_editorial_queue as queue
from process_lock import process_lock
from translate import read_json, save_json


def apply_edits(rows, candidate, edits):
    revised = copy.deepcopy(candidate)
    by_id = {row['id']: row for row in rows}
    cues = {cue['id']: cue for cue in revised['cues']}
    if len(cues) != len(revised['cues']) or len(by_id) != len(rows) or set(by_id) != set(cues):
        raise ValueError('Source/candidate cue scope differs')
    seen = set()
    if not edits:
        raise ValueError('Explicit reviewed edits required')
    for edit in edits:
        key = edit['id']
        if key in seen or key not in cues:
            raise ValueError('Duplicate or unknown edit cue')
        seen.add(key)
        if by_id[key]['text'] != edit['source_text'] or cues[key]['translation'] != edit['baseline_translation']:
            raise ValueError('Source or baseline translation changed')
        if not isinstance(edit['translation'], str) or not edit['translation'].strip():
            raise ValueError('Nonempty production wording required')
        cues[key]['translation'] = edit['translation']
    return revised


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Business text export runs on Windows')
    plan_bytes = args.plan.read_bytes()
    plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    plan = json.loads(plan_bytes.decode("utf-8-sig"))
    project, episode = plan['project_id'], plan['episode']
    if (type(project) is not int or project not in queue.COUNTS or type(episode) is not int
        or not 1 <= episode <= queue.COUNTS[project] or plan['independent_edits_approved'] is not True):
        raise ValueError('Invalid reviewed edit scope')
    folder = queue.folder_for(project, episode)
    out = folder.parent / 'editorial-production-candidate-20261031-v2'
    with process_lock(folder / 'editorial.lock', timeout=60):
        ready = queue.validate_saved_locked(project, episode, folder)
        if (ready['result_sha256'] != plan['baseline_result_sha256']
            or ready['subtitle_sha256'] != plan['baseline_subtitle_sha256']
            or queue.digest(folder / 'source-input.private.json') != plan['source_input_sha256']
            or queue.digest(plan['audit_report_path']) != plan['audit_report_sha256']):
            raise ValueError('Reviewed source, baseline, or audit changed')
        context = read_json(folder / 'source-input.private.json')
        baseline = read_json(folder / 'editorial-result.private.json')
        revised = apply_edits(context['timed_source'], baseline['candidate'], plan['edits'])
        import prepare_review_episode_editorial as worker
        worker.validate(revised, context['timed_source'], context)
        body = worker.candidate_srt(context['timed_source'], revised)
        data = {'project_id': project, 'episode': episode, 'candidate': revised,
                'baseline_result_sha256': ready['result_sha256'],
                'baseline_subtitle_sha256': ready['subtitle_sha256'],
                'source_input_sha256': plan['source_input_sha256'],
                'edit_plan_sha256': plan_sha256,
                'audit_report_sha256': plan['audit_report_sha256'],
                'independent_text_edits_approved': True, 'baseline_model_receipts_unchanged': True,
                'native_listening_passed': False, 'audio_speaker_verified': False, 'tts_ready': False}
        if queue.digest(args.plan) != plan_sha256:
            raise ValueError('Edit plan changed during export')
        out.mkdir(exist_ok=True)
        subtitle = out / 'pt-BR-production-candidate.srt'
        result = out / 'editorial-production.private.json'
        if subtitle.exists() and subtitle.read_bytes() != body:
            raise ValueError('Existing production subtitle differs; preserve it')
        if result.exists() and read_json(result) != {**data, 'subtitle_sha256': queue.digest(subtitle)}:
            raise ValueError('Existing production text differs; preserve it')
        if not subtitle.exists():
            subtitle.write_bytes(body)
        data['subtitle_sha256'] = queue.digest(subtitle)
        if not result.exists():
            save_json(result, data)
        print(f'EXPORTED {project} EP{episode:02d}: {len(plan["edits"])} reviewed edit(s); original IDs/times preserved')


if __name__ == '__main__':
    main()
