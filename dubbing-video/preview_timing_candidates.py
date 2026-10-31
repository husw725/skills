"""Measure reviewed audio placement trials using existing WAVs, without speech service calls."""
import argparse
import math
from pathlib import Path
import sys

from dub_episode import RATE, digest, probe, read_audio, run, trim_edges, write_audio
from process_lock import process_lock
from translate import read_json, save_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', required=True, type=Path)
    p.add_argument('--audit-sha256', required=True)
    p.add_argument('--inputs', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--ffmpeg', required=True, type=Path)
    args = p.parse_args()
    if sys.platform != 'win32': raise ValueError('Windows audio processing only')
    if digest(args.audit) != args.audit_sha256: raise ValueError('Reviewed trial proposals changed')
    audit = read_json(args.audit)
    if digest(args.inputs) != audit['input_sha256']: raise ValueError('Pinned production inputs changed')
    frozen = {(r['episode'], r['group']['id']): r for r in read_json(args.inputs)['groups']}
    rows = [r for r in audit['rows'] if r['route'] == 'free_independent_preroll_trial']
    if not 1 <= len(rows) <= 18: raise ValueError('Bounded single-group trial scope required')
    # Output is a separate preview; neither production plans nor paid cache are edited.
    if not args.out.resolve().is_relative_to(Path('output').resolve()):
        raise ValueError('Preview must stay in ignored output')
    args.out.mkdir(parents=True, exist_ok=True)
    with process_lock(args.out/'preview.lock', timeout=0):
        summary = []
        for row in rows:
            item = frozen[row['episode'], row['id']]
            root = Path(item['root']); path = root/'speech-plan.private.json'
            if digest(path) != item['plan_sha256']: raise ValueError('Original production plan changed')
            plan = read_json(path)
            group = next(g for g in plan['groups'] if g['id'] == row['id'])
            if group != item['group']: raise ValueError('Original speech group changed')
            generated = read_json(root/'generation-result.private.json')
            if generated['plan_sha256'] != digest(path): raise ValueError('Generation version changed')
            raw = next(g for g in generated['groups'] if g['group_id'] == row['id'])
            if raw != row['paid_raw'] or digest(raw['raw_path']) != raw['raw_sha256']:
                raise ValueError('Existing paid raw differs from reviewed evidence')
            start = row['simple_trial_start_at_1_19']; end = row['current_end_limit']
            if (not row['simple_trial_does_not_overlap_actual_prior']
                    or not 0 <= start < group['start'] < end
                    or start + .000001 < row['earliest_with_actual_previous_and_080_gap']):
                raise ValueError('Candidate lacks independent prior-voice gap')
            audio, left, right = trim_edges(read_audio(Path(raw['raw_path']), args.ffmpeg))
            seconds = len(audio)/RATE
            tempo = max(1., seconds/(end-start))
            if not math.isfinite(tempo) or tempo > 1.2: raise ValueError('Trial exceeds tempo bound')
            folder = args.out/row['id']; folder.mkdir(exist_ok=True)
            binding = dict(plan_sha256=digest(path), raw_sha256=raw['raw_sha256'],
                           start=start, end_limit=end, post_atempo=tempo,
                           source_start=group['start'], source_end=group['end'])
            marker = folder/'binding.private.json'; receipt = folder/'receipt.private.json'
            target = folder/'trial.wav'
            if marker.exists() and read_json(marker) != binding: raise ValueError('Prior preview changed')
            if receipt.exists():
                saved = read_json(receipt)
                if digest(target) != saved['sha256']: raise ValueError('Prior preview WAV changed')
            else:
                if target.exists(): raise ValueError('Orphan preview WAV; preserve for inspection')
                save_json(marker, binding)
                trimmed = folder/'trimmed.wav'
                if not trimmed.exists(): write_audio(trimmed, audio)
                run([args.ffmpeg, '-nostdin', '-v', 'error', '-n', '-i', trimmed,
                     '-af', f'atempo={tempo:.12f}', '-ar', str(RATE), '-ac', '1',
                     '-c:a', 'pcm_s16le', target])
                actual = float(probe(target, args.ffmpeg)['format']['duration'])
                saved = dict(id=row['id'], episode=row['episode'], path=str(target),
                             sha256=digest(target), seconds=actual, start=start, end=start+actual,
                             end_limit=end, post_atempo=tempo,
                             nominal_combined_rate=group['request']['speed']*tempo,
                             edge_trim_seconds=[left, right],
                             technical_window_passed=start+actual <= end+.02,
                             source_picture_alignment_verified=False, native_listening_passed=False,
                             new_tts=0, new_clones=0)
                save_json(receipt, saved)
            summary.append(saved)
            save_json(args.out/'progress.private.json', dict(stage='zero_tts_timing_preview',
                      completed=len(summary), total=len(rows), new_tts=0, new_clones=0))
        save_json(args.out/'summary.private.json', dict(rows=summary, new_tts=0, new_clones=0,
                  technical_passed=sum(r['technical_window_passed'] for r in summary),
                  formal_decisions_modified=False, source_picture_alignment_verified=False,
                  native_listening_passed=False))
        print('ZERO_TTS_TIMING_PREVIEWS', len(summary), 'TECHNICAL_PASS',
              sum(r['technical_window_passed'] for r in summary))


if __name__ == '__main__': main()
