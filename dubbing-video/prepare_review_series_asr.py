"""Offline series source evidence for a pinned collection; no translation/voice API."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import wave
import numpy as np
from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json, fingerprint, write_srt
from review_drama_source_asr import ROOT, MANIFEST_FINGERPRINT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32' or not args.ffmpeg.is_file():
        raise ValueError('Windows local FFmpeg required')
    output = ROOT / 'series-source-asr'
    output.mkdir(exist_ok=True)
    with process_lock(output / 'worker.lock', timeout=0):
        manifest = read_json(ROOT / 'intake-manifest.private.json')
        if fingerprint(manifest) != MANIFEST_FINGERPRINT:
            raise ValueError('Pinned source batch changed')
        videos = [x for x in manifest['items'] if x['kind'] == 'video'
            and not (x['project_id'] == 100 and x['variant'] == 'nosub_label_not_visual_verification')]
        if len(videos) != 136:
            raise ValueError('Series evidence scope changed')
        videos.sort(key=lambda x: (x['project_id'] != 100, x['project_id'], x['episode'], x['asset_id']))
        local = Path('output/tools/source-asr-models/large-v3')
        official = read_json(local / 'official-source.json')
        verified = read_json(local / 'verified.json')
        model_sha = next(x['lfs']['sha256'] for x in official['siblings'] if x['rfilename'] == 'model.bin')
        if (verified.get('official_hashes_verified') is not True
                or verified['revision'] != official['revision']
                or verified['repo'] != 'Systran/faster-whisper-large-v3'
                or digest(local / 'model.bin') != model_sha):
            raise ValueError('Pinned offline model required')
        from faster_whisper import WhisperModel
        model = WhisperModel(str(local.resolve()), local_files_only=True, device='cpu', compute_type='int8',
            cpu_threads=6, num_workers=1)
        decode = {'language': 'en', 'beam_size': 5, 'temperature': 0,
            'condition_on_previous_text': False, 'vad_filter': False, 'word_timestamps': True}
        progress = output / 'progress.private.json'
        state = {'stage': 'preparing_series_source_evidence', 'total': len(videos),
            'completed': {}, 'errors': {}, 'voice_generation_started': False,
            'native_listening_passed': False}
        save_json(progress, state)
        for item in videos:
            pid, aid, version = item['project_id'], item['asset_id'], item['version']
            key = f'{pid}:{aid}:{version}'
            try:
                prep = Path('output') / f'review-project-{pid}/source-preparation'
                inspection = read_json(prep / f'asset-{aid}-v{version}.private.json')
                if tuple(inspection['source_asset'][k] for k in ('project_id','asset_id','version')) != (pid,aid,version):
                    raise ValueError('Inspection belongs to another source')
                source = Path(inspection['source_asset']['path'])
                source_sha = digest(source)
                if source_sha != inspection['source_sha256']:
                    raise ValueError('Source video changed')
                folder = output / f'project-{pid}/asset-{aid}-v{version}'
                folder.mkdir(parents=True, exist_ok=True)
                binding = {'source_sha256': source_sha, 'model_sha256': model_sha,
                    'model_revision': verified['revision'], 'decoding': decode}
                report_path = folder / 'source-asr.private.json'
                receipt_path = folder / 'source-asr.receipt.private.json'
                if report_path.exists():
                    report = read_json(report_path)
                    if (not receipt_path.exists() or read_json(receipt_path)!=
                            {'binding':binding,'report_sha256':digest(report_path)}
                            or report['binding'] != binding
                            or (report['project_id'],report['asset_id'],report['version'],report['variant']) !=
                                (pid,aid,version,item['variant'])
                            or any(report[x] is not False for x in ('original_subtitle','source_speaker_verified',
                                'screenplay_reviewed','native_listening_passed','tts_ready'))
                            or digest(folder/'source-16k.wav')!=report['audio_sha256']):
                        raise ValueError('Prior ASR evidence changed')
                else:
                    audio = folder / 'source-16k.wav'
                    # This WAV is an expendable derivative in this worker's own namespace.
                    part = folder / 'source-16k.part.wav'
                    completed = subprocess.run([str(args.ffmpeg), '-nostdin', '-v', 'error',
                        '-y', '-i', str(source), '-vn', '-ar', '16000', '-ac', '1',
                        '-c:a', 'pcm_s16le', str(part)], capture_output=True, timeout=300)
                    if completed.returncode:
                        raise ValueError('Source audio extraction failed')
                    part.replace(audio)
                    with wave.open(str(audio), 'rb') as stream:
                        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                            raise ValueError('Unexpected PCM format')
                        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype('float32') / 32768
                    segments, _ = model.transcribe(samples, **decode)
                    rows = [{'id': f'p{pid}-a{aid}-{i}', 'episode': str(item['episode']),
                        'start': s.start, 'end': s.end, 'text': s.text.strip(),
                        'words': [{'word': w.word, 'start': w.start, 'end': w.end,
                            'probability': w.probability} for w in s.words or []]}
                        for i, s in enumerate(segments, 1)]
                    report = {'binding': binding, 'project_id': pid, 'asset_id': aid,
                        'version': version, 'variant': item['variant'], 'segments': rows,
                        'audio_sha256': digest(audio), 'original_subtitle': False,
                        'source_speaker_verified': False, 'screenplay_reviewed': False,
                        'native_listening_passed': False, 'tts_ready': False}
                    save_json(report_path, report)
                    save_json(receipt_path, {'binding':binding,'report_sha256':digest(report_path)})
                write_srt(folder / 'source-en-machine-draft.srt',
                    [{**r, 'translation': r['text']} for r in report['segments']])
                state['completed'][key] = {'report': str(report_path), 'sha256': digest(report_path)}
            except Exception as exc:
                state['errors'][key] = {'error_type': type(exc).__name__}
                import traceback
                traceback.print_exc()
            state['updated_at'] = time.time()
            save_json(progress, state)
        state['stage'] = 'source_evidence_complete_review_pending' if not state['errors'] else 'source_evidence_partial_needs_review'
        save_json(progress, state)


if __name__ == '__main__':
    out = ROOT / 'series-source-asr'
    out.mkdir(exist_ok=True)
    sys.stdout = (out / 'worker.log').open('a', encoding='utf-8', buffering=1)
    sys.stderr = sys.stdout
    main()
