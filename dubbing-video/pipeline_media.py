"""Local per-episode original-track binding or Demucs preparation, with no paid calls."""
import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

from dub_episode import digest, probe, run
from process_lock import process_lock
from translate import read_json, save_json, fingerprint
from review_drama_source_asr import MANIFEST_FINGERPRINT
from prepare_review_editorial_queue import COUNTS


def source_media(project, episode):
    manifest = read_json('output/four-dramas-20261030/intake-manifest.private.json')
    if fingerprint(manifest) != MANIFEST_FINGERPRINT:
        raise ValueError('Source batch changed')
    variant = 'nosub_label_not_visual_verification' if project == 100 else 'current_review_reference'
    choices = [x for x in manifest['items'] if x['project_id'] == project and x['kind'] == 'video'
               and x['episode'] == episode and x['variant'] == variant]
    if len(choices) != 1:
        raise ValueError('Source cut ambiguous')
    item = choices[0]
    inspected = read_json(Path(f'output/review-project-{project}/source-preparation') /
                          f'asset-{item["asset_id"]}-v{item["version"]}.private.json')
    if any(inspected['source_asset'][k] != item[k] for k in ('project_id', 'asset_id', 'version')):
        raise ValueError('Inspection scope differs')
    video = Path(inspected['source_asset']['path'])
    if digest(video) != inspected['source_sha256']:
        raise ValueError('Original video changed')
    tracks = {}
    if project == 100:
        assets = read_json('output/review-project-100/netdisk-source-preparation/progress.private.json')['assets']
        for kind in ('sfx', 'dialog'):
            matches = [a for a in assets.values() if a['kind'] == kind and a['episode'] == episode]
            if len(matches) != 1 or digest(matches[0]['path']) != matches[0]['sha256']:
                raise ValueError('Original supplied audio changed or ambiguous')
            tracks[kind] = matches[0]
    return video, inspected['source_sha256'], tracks


def prepare(project, episode, ffmpeg, device):
    revision = 'pipeline-media-20261031' if project == 100 else 'pipeline-media-20261031-v2'
    root = Path(f'output/review-project-{project}/episode-{episode:02d}/{revision}')
    root.mkdir(parents=True, exist_ok=True)
    with process_lock(root / 'media.lock', timeout=0):
        video, sha, tracks = source_media(project, episode)
        binding = {'project_id': project, 'episode': episode, 'video': str(video), 'video_sha256': sha}
        receipt = root / 'media.private.json'
        if receipt.exists():
            old = read_json(receipt)
            if old['source'] != binding or any(digest(p) != h for p, h in old['output_sha256'].items()):
                raise ValueError('Existing media binding changed')
            return old
        if tracks:
            background, dialogue = Path(tracks['sfx']['path']), Path(tracks['dialog']['path'])
            recipe = {'kind': 'supplied_sfx_and_dialogue', 'pure_background_verified': False}
        else:
            checkpoint = Path.home()/'.cache/torch/hub/checkpoints/955717e8-8726e21a.th'
            if not checkpoint.is_file():
                raise ValueError('Pinned cached htdemucs checkpoint missing; no implicit model download')
            model_sha = digest(checkpoint)
            if not model_sha.startswith('8726e21a'):
                raise ValueError('Cached htdemucs checksum differs from official filename')
            source = root / 'source-stereo.wav'
            run([ffmpeg,'-nostdin','-v','error','-y','-i',video,'-vn','-ar','44100','-ac','2','-c:a','pcm_s16le',source])
            recipe = {'kind':'demucs_htdemucs_candidate','model_sha256':model_sha,'shifts':0,'segment':7,
                      'overlap':0.25,'pure_background_verified':False,'source_speaker_verified':False}
            marker = root/'separation-input.private.json'
            proposed = {'source':binding,'recipe':recipe,'source_wav_sha256':digest(source)}
            if marker.exists() and read_json(marker) != proposed:
                raise ValueError('Separation input changed')
            save_json(marker, proposed)
            destination = root/'separated'
            import torch
            actual_device = 'cuda' if device == 'cuda' and torch.cuda.is_available() else 'cpu'
            command = [sys.executable,'-m','demucs','-n','htdemucs','--two-stems','vocals',
                       '--shifts','0','--overlap','0.25','--segment','7','-d',actual_device,
                       '--float32','-j','0','-o',str(destination),str(source)]
            save_json(root/'progress.private.json',{'stage':'separating_background_and_dialogue','updated_at':time.time()})
            with process_lock(Path('output/four-dramas-20261030/separation-resource.lock'),timeout=3600):
                with (root/'separation.private.log').open('a',encoding='utf-8') as log:
                    result = subprocess.run(command,stdout=log,stderr=log,timeout=3600)
                if result.returncode:
                    raise ValueError('Local separation failed; see private log')
            background = destination/'htdemucs/source-stereo/no_vocals.wav'
            dialogue = destination/'htdemucs/source-stereo/vocals.wav'
        video_seconds = float(probe(video,ffmpeg)['format']['duration'])
        info = {}
        for label,path in (('background',background),('dialogue',dialogue)):
            run([ffmpeg,'-nostdin','-v','error','-xerror','-i',path,'-f','null','-'])
            duration = float(probe(path,ffmpeg)['format']['duration'])
            if abs(duration-video_seconds) > 0.2:
                raise ValueError('Media track duration differs; inspect actual cut')
            info[label] = {'path':str(path),'sha256':digest(path),'seconds':duration}
        value = {'source':binding,'recipe':recipe,**info,'video_seconds':video_seconds,
                 'output_sha256':{v['path']:v['sha256'] for v in info.values()},
                 'native_listening_passed':False,'full_timeline_alignment_verified':False}
        save_json(receipt,value)
        save_json(root/'progress.private.json',{'stage':'media_candidates_ready','updated_at':time.time()})
        return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=int,choices=tuple(COUNTS))
    parser.add_argument('--episode',type=int)
    parser.add_argument('--ffmpeg',type=Path,required=True)
    parser.add_argument('--device',choices=('cpu','cuda'),default='cpu')
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows media preparation only')
    projects=[args.project] if args.project else [96,110,102,100]
    state_path=Path('output/four-dramas-20261030/media-pipeline-progress.private.json')
    with process_lock(state_path.with_suffix('.lock'),timeout=0):
        state={'episodes':{},'paid_calls':0}
        for episode in ([args.episode] if args.episode else range(1,38)):
            for project in projects:
                if not 1<=episode<=COUNTS[project]:continue
                key=f'{project}:{episode}'
                state.update(current=key,stage='preparing_media',updated_at=time.time());save_json(state_path,state)
                try:
                    media=prepare(project,episode,args.ffmpeg,args.device)
                    state['episodes'][key]={'status':'media_candidates_ready','background_sha256':media['background']['sha256']}
                except Exception as exc:
                    state['episodes'][key]={'status':'needs_review','error_type':type(exc).__name__}
                    import traceback
                    revision = 'pipeline-media-20261031' if project == 100 else 'pipeline-media-20261031-v2'
                    folder=Path(f'output/review-project-{project}/episode-{episode:02d}/{revision}');folder.mkdir(parents=True,exist_ok=True)
                    with (folder/'error.private.log').open('a',encoding='utf-8') as log:traceback.print_exc(file=log)
                save_json(state_path,state)
        state.update(stage='media_preparation_finished',updated_at=time.time());save_json(state_path,state)


if __name__=='__main__':main()
