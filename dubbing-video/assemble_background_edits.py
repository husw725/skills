"""Assemble explicit same-drama M&E edits into a new background; no API or TTS."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json

RATE = 48000


def layout(spec):
    duration = spec.get('duration')
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid picture duration')
    total = round(duration*RATE);previous = 0;result = []
    for segment in spec['segments']:
        values = [segment[k] for k in ('target_start', 'target_end', 'source_start')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('Invalid segment time')
        start, end, source = [round(x*RATE) for x in values]
        if start != previous or end <= start or end > total or source < 0:
            raise ValueError('Background edits must partition the full picture without gaps/overlaps')
        if not segment.get('basis') or not segment.get('source'):
            raise ValueError('Missing source/edit basis')
        result.append((segment, start, end, source));previous = end
    if previous != total:
        raise ValueError('Incomplete background coverage')
    return total, result


def assemble(spec, root):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    total, segments = layout(spec)
    fade = spec.get('edge_fade_ms', 8)
    if isinstance(fade, bool) or not isinstance(fade, (int, float)) or not math.isfinite(fade) or not 0 <= fade <= 20:
        raise ValueError('Only short click-suppression edge fades allowed')
    sources = {};padded = []
    for segment, _, _, _ in segments:
        item = segment['source'];path = str(item['path'])
        if digest(path) != item['sha256']:
            raise ValueError('Bound source changed')
        if path not in sources:
            samples, rate = sf.read(path, dtype='float32', always_2d=True)
            if samples.shape[1] != 2 or not np.isfinite(samples).all():
                raise ValueError('Expected finite stereo M&E')
            divisor = math.gcd(rate, RATE)
            sources[path] = resample_poly(samples, RATE//divisor, rate//divisor).astype('float32') if rate != RATE else samples
    output = np.zeros((total, 2), dtype='float32')
    for segment, start, end, source in segments:
        samples = sources[str(segment['source']['path'])];needed = end-start
        if source >= len(samples):
            raise ValueError('Source interval starts outside media')
        piece = samples[source:source+needed].copy()
        missing = needed-len(piece)
        if missing:
            allowed = segment.get('tail_pad_seconds', 0)
            if isinstance(allowed, bool) or not isinstance(allowed, (int, float)) or not math.isfinite(allowed) or not 0 <= allowed <= .05 or missing > round(allowed*RATE):
                raise ValueError('Source tail unavailable without explicit short-pad policy')
            padded.append({'target_start': (start+len(piece))/RATE, 'seconds': missing/RATE})
        n = min(round(fade*RATE/1000), len(piece)//2)
        if n:
            # Fade real samples BEFORE padding, never only the appended zeros.
            ramp = np.linspace(0, 1, n, dtype='float32')[:, None]
            if start > 0:piece[:n] *= ramp
            if end < total or missing:piece[-n:] *= ramp[::-1]
        if missing:
            piece = np.pad(piece, ((0, missing), (0, 0)))
        output[start:end] = piece
    root = Path(root);root.mkdir(parents=True, exist_ok=True)
    attempt = root/f'attempt-{uuid.uuid4().hex}';attempt.mkdir()
    path = attempt/'background-edited.wav';sf.write(path, output, RATE, subtype='FLOAT')
    for segment, _, _, _ in segments:
        if digest(segment['source']['path']) != segment['source']['sha256']:
            raise ValueError('Source changed while assembling')
    proof = {'episode': spec['episode'], 'recipe': spec, 'output': str(path), 'output_sha256': digest(path),
             'sample_rate': RATE, 'samples': total, 'channels': 2, 'explicit_tail_padding': padded,
             'edit_policy': 'disclosed source switches with short amplitude edge fades, no music stretching or loops',
             'background_listening_passed': False, 'native_listening_passed': False,
             'new_tts': 0, 'new_clones': 0}
    save_json(attempt/'assembly-receipt.private.json', proof)
    return proof, attempt/'assembly-receipt.private.json'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source-audit', type=Path, required=True)
    a = p.parse_args()
    if sys.platform != 'win32':raise ValueError('Media execution runs on Windows')
    audit = read_json(a.source_audit)
    manifest_bytes = a.manifest.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    specs = json.loads(manifest_bytes.decode('utf-8-sig'))['episodes']
    eps = [x['episode'] for x in specs]
    if len(eps) != len(set(eps)) or not eps:raise ValueError('Invalid scope')
    if audit.get('manifest_sha256') != manifest_sha or audit.get('technical_edit_scope_approved') is not True or set(audit['approved_episodes']) != set(eps):
        raise ValueError('Independent source/edit review required')
    with process_lock(a.output/'assembly.lock', timeout=0):
        progress = a.output/'progress.private.json'
        if progress.exists():raise ValueError('Prior assembly exists; inspect its receipts rather than overwrite')
        state = {'manifest_sha256': manifest_sha, 'source_audit_sha256': digest(a.source_audit), 'episodes': {}}
        save_json(progress, state)
        for spec in specs:
            proof, receipt = assemble(spec, a.output/f'episode-{spec["episode"]:02d}')
            state['episodes'][str(spec['episode'])] = {'status': 'background_edit_candidate', 'receipt': str(receipt), 'receipt_sha256': digest(receipt), 'background': {'path': proof['output'], 'sha256': proof['output_sha256']}}
            save_json(progress, state);print('BACKGROUND_EDIT', spec['episode'], flush=True)


if __name__ == '__main__':main()
