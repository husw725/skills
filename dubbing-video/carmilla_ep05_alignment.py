"""Narrow production placement policy for the EP05 written diary/inner voiceover."""

def validate_group(episode, unit):
    if episode != 5:
        raise ValueError('EP05 production placement cannot apply to another episode')
    specs = [
        (['e05-23', 'e05-16', 'e05-17'], 'Mother', 62.566, 68.333, 'diary'),
        (['e05-18', 'e05-19'], 'Laura', 68.866, 74.4, 'inner_vo'),
    ]
    for ids, role, start, end, kind in specs:
        if set(ids) & set(unit['cue_ids']):
            if (unit['cue_ids'], unit['production_voice'], unit['start'], unit['end']) != (ids, role, start, end):
                raise ValueError('Exact reviewed source group/casting/window required')
            return kind
    return None


def vo_window(natural, unit, previous_end):
    if validate_group(5, unit) != 'inner_vo':
        raise ValueError('Only this inner VO may enter the preceding production gap')
    if previous_end > 68.475001:
        raise ValueError('Diary must finish with at least 100ms before inner VO')
    start = 68.575
    target = 74.4 - start
    return start, target, max(1., natural / target)


def verify_basis(folder, plan):
    from pathlib import Path
    from dub_episode import digest
    from translate import read_json, fingerprint
    from rerun_carmilla_season import SPEECH_ROOT, SPEECH2_ROOT
    basis=read_json(folder/'audio-boundary-basis.private.json')
    if read_json(folder/'audio-boundary-basis.json')['fingerprint']!=fingerprint(basis):
        raise ValueError('Full alignment basis differs from immutable fingerprint')
    if basis['plan_sha256']!=digest(folder/'plan.json'):
        raise ValueError('Reviewed alignment plan changed')
    audit=basis['audit_report'];board=basis['storyboard']
    if digest(Path(audit['path']))!=audit['sha256']:
        raise ValueError('Independent alignment audit changed')
    board_path=Path('input/drama-01/storyboard/final.html')
    if Path(board['path'])!=board_path or digest(board_path)!=board['sha256'] or plan['input_sha256'][str(board_path)]!=board['sha256']:
        raise ValueError('Mapped final storyboard changed')
    if (plan['episode'],plan['project_id'])!=(5,59) or len(plan['units'])!=32:
        raise ValueError('Precise approved plan scope required')
    if validate_group(5,plan['units'][15])!='diary' or validate_group(5,plan['units'][16])!='inner_vo':
        raise ValueError('Adjacent diary and inner VO required')
    following=plan['units'][17]
    if following['cue_ids']!=['e05-20'] or following['start']!=74.4 or following['production_voice']!='Carmilla':
        raise ValueError('Next dialogue boundary changed')
    expected=[SPEECH_ROOT/'episode-05/utterances/e05-group-016/original.wav',
              SPEECH2_ROOT/'episode-05/utterances/e05-group-017/original.wav']
    if {Path(a['path']) for a in basis['audio']}!=set(expected):
        raise ValueError('Only the exact existing paid diary and VO may seed this alignment')
    for a in basis['audio']:
        path=Path(a['path'])
        if digest(path)!=a['sha256'] or read_json(path.with_name('audio-receipt.json'))['sha256']!=a['sha256']:
            raise ValueError('Paid source audio changed')
    return basis


def completed_audio(folder, request):
    from dub_episode import digest
    from translate import read_json, fingerprint
    path=folder/'original.wav'
    receipt=read_json(folder/'audio-receipt.json')
    if not receipt.get('task_id') or receipt.get('request_fingerprint')!=fingerprint(request) or digest(path)!=receipt.get('sha256'):
        raise ValueError('Exact completed paid audio required; no synthesis permitted')
    return path, receipt
