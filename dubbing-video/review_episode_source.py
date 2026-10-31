"""Read pinned original subtitles or clearly identified offline ASR evidence."""
from pathlib import Path
import re
from dub_episode import digest
from translate import read_json, fingerprint
from review_drama_source_asr import MANIFEST_FINGERPRINT

EPISODE_COUNTS = {96: 30, 100: 32, 102: 37, 110: 35}


def episode_rows(project, episode):
    if type(project) is not int or project not in EPISODE_COUNTS or type(episode) is not int or not 1 <= episode <= EPISODE_COUNTS[project]:
        raise ValueError('Unsupported drama or episode')
    if project == 100:
        source = read_json('output/review-project-100/subtitles/dialogue.en.json')['segments']
        if len(source) != 854:
            raise ValueError('Original subtitle corpus changed')
        rows = [r for r in source if int(r['episode']) == episode]
        if not rows or (episode == 1 and len(rows) != 44):
            raise ValueError('Original episode scope changed')
        # Match the existing Count context payload exactly; raw-import metadata stays at source.
        return [{k:r[k] for k in ('id','episode','start','end','text')} for r in rows], None
    manifest = read_json('output/four-dramas-20261030/intake-manifest.private.json')
    if fingerprint(manifest) != MANIFEST_FINGERPRINT:
        raise ValueError('Pinned source collection changed')
    choices = [i for i in manifest['items'] if i['project_id'] == project and i['kind'] == 'video'
        and i['episode'] == episode and i['variant'] == 'current_review_reference']
    if len(choices) != 1:
        raise ValueError('Episode cut requires source reconciliation')
    item = choices[0]
    folder = Path('output/four-dramas-20261030/series-source-asr') / f'project-{project}/asset-{item["asset_id"]}-v{item["version"]}'
    path = folder / 'source-asr.private.json'
    report = read_json(path)
    if read_json(folder / 'source-asr.receipt.private.json') != {'binding': report['binding'], 'report_sha256': digest(path)}:
        raise ValueError('ASR receipt differs from source evidence')
    if (report['project_id'], report['asset_id'], report['version'], report['variant']) != (
            project, item['asset_id'], item['version'], item['variant']):
        raise ValueError('Wrong ASR source identity')
    if any(report[k] is not False for k in ('original_subtitle', 'source_speaker_verified',
            'screenplay_reviewed', 'native_listening_passed', 'tts_ready')):
        raise ValueError('ASR evidence is not an approved subtitle or speaker identity')
    local=Path('output/tools/source-asr-models/large-v3')
    official=read_json(local/'official-source.json');verified=read_json(local/'verified.json')
    model_sha=next(x['lfs']['sha256'] for x in official['siblings'] if x['rfilename']=='model.bin')
    expected_decode={'language':'en','beam_size':5,'temperature':0,
        'condition_on_previous_text':False,'vad_filter':False,'word_timestamps':True}
    if (verified.get('official_hashes_verified') is not True
      or verified['repo']!='Systran/faster-whisper-large-v3' or verified['revision']!=official['revision']
      or report['binding']['model_sha256']!=model_sha or report['binding']['model_revision']!=verified['revision']
      or fingerprint(report['binding']['decoding'])!=fingerprint(expected_decode)):
        raise ValueError('ASR model or English decoding is outside the verified source recipe')
    inspection = read_json(Path(f'output/review-project-{project}/source-preparation') /
        f'asset-{item["asset_id"]}-v{item["version"]}.private.json')
    if tuple(inspection['source_asset'][k] for k in ('project_id','asset_id','version')) != (project,item['asset_id'],item['version']):
        raise ValueError('Inspection belongs to another source asset')
    original = Path(inspection['source_asset']['path'])
    if (digest(original) != report['binding']['source_sha256']
            or inspection['source_sha256'] != report['binding']['source_sha256']
            or digest(folder / 'source-16k.wav') != report['audio_sha256']):
        raise ValueError('Physical ASR source changed')
    rows = report['segments']
    if not rows or any(int(r['episode']) != episode or not re.fullmatch(fr'p{project}-a{item["asset_id"]}-[0-9]+',r['id']) for r in rows):
        raise ValueError('Empty or wrong source episode')
    return rows, {'path': str(path), 'sha256': digest(path), 'video_sha256': report['binding']['source_sha256'],
        'model_sha256':model_sha,'model_revision':verified['revision'],'audio_sha256':report['audio_sha256'],
        'kind': 'machine_asr_draft_not_original_subtitles', 'original_subtitle_available': False,
        'speaker_audio_verified': False, 'source_dialogue_manually_verified': False}
