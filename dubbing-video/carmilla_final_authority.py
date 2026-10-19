"""Two explicit user decisions against the matched final storyboard; retain source evidence."""
from pathlib import Path

SPECS={
    8: {'e08-6':('is this really even for her',28.266,29.6,'Does this really involve her?','Tem mesmo a ver com ela?')},
    29:{'e29-8':('How many years.',47.4,48.433,'Her minions…','Os capangas dela…'),
        'e29-19':('No chance the castle is secure.',81.9,84.2,'No chance. The castle is secure.','Sem chance. O castelo está seguro.')},
}


def reconstruct(n, rows, reference, evidence, authority):
    from dub_episode import digest
    from translate import read_json
    from rerun_carmilla_season import reading_tokens, STORYBOARD_MAPPING_SHA256
    if (n not in SPECS or authority.get('kind')!='user_final_storyboard_editorial_resolution'
            or authority.get('user_instruction')!='按final来定'
            or authority.get('approved_source_cues')!=['e08-6','e29-8']
            or authority.get('storyboard_sha256')!=STORYBOARD_MAPPING_SHA256
            or authority.get('audio_listened') is not False or authority.get('speaker_verified') is not False):
        raise ValueError('Explicit user decision for only the two disputed cues required')
    audit=authority['audit_report']
    if digest(Path(audit['path']))!=audit['sha256']:
        raise ValueError('Independent final-storyboard audit changed')
    subtitle=authority['original_subtitle'];subtitle_path=Path(subtitle['path'])
    expected_name='carmilla_Ep08.srt' if n==8 else 'Carmilla_EP29.srt'
    expected_path=Path('input/drama-01/subtitles/original/短剧/carmilla/06SRT字幕')/expected_name
    if subtitle_path!=expected_path or digest(subtitle_path)!=subtitle['sha256']:
        raise ValueError('Original physical subtitle changed')
    packet=authority['evidence_packet']
    if digest(Path(packet['path']))!=packet['sha256']:
        raise ValueError('Reviewed source evidence packet changed')
    expected={'e08-6'} if n==8 else {'e29-8','e29-19'}
    if set(evidence)!=expected or set(authority['approved_translations'])!=set(SPECS[n]):
        raise ValueError('Exact source review and translation scope required')
    expected_entry='EP-08' if n==8 else 'EP-30'
    if [e['storyboard_episode'] for e in reference['entries']]!=[expected_entry]:
        raise ValueError('Dialogue mapping changed')
    board_tokens=reading_tokens(reference['entries'][0]['storyboard']);by={r['id']:r for r in rows};result={}
    for cue,(original,start,end,reading,pt) in SPECS[n].items():
        row=by[cue]
        if (row['text'],row['start'],row['end'])!=(original,start,end):
            raise ValueError('Original caption/window changed')
        wanted=reading_tokens(reading)
        if not any(board_tokens[i:i+len(wanted)]==wanted for i in range(len(board_tokens)-len(wanted)+1)):
            raise ValueError('Exact mapped final dialogue missing')
        if authority['approved_translations'][cue]!=pt:
            raise ValueError('Independently reviewed translation changed')
        source=evidence[cue]
        if source['cue']!=row or set(source['models'])!={'small.en','medium.en'} or source['source_speaker_verified'] is not False:
            raise ValueError('Archived original evidence scope changed')
        result[cue]={'original_subtitle_text':original,'editorial_reading':reading,
            'source_basis':'editorial_subtitle_confirmation' if cue=='e29-19' else 'user_authorized_final_storyboard_resolution',
            'reference_episode':expected_entry,'reference_sha256':STORYBOARD_MAPPING_SHA256,
            'user_instruction':authority['user_instruction'],'complete_asr_records':source['models'],
            'human_listened':False,'source_speaker_verified':False,
            'note':'Original caption/timecodes and conflicting ASR retained. Editorial meaning decision, not acoustic confirmation. '
                   'For e29-19, existing meaning remains unchanged; full ASR tail exceeds subtitle display window.'}
    return result
