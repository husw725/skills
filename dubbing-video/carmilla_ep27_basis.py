"""Versioned editorial reconstruction from original captions and two ASR tails."""
import math
from collections import Counter
from rerun_carmilla_season import reading_tokens

SPECS={
    'e27-12':("Irina’s cursed power will strike when you’",30.566,32.8,
        "Irina's cursed power will strike when you're at your weakest.",
        "will strike when you're at your weakest",'e27-20'),
    'e27-2':('The seven-day sealing ritual is',72.6,74.266,
        'The seven-day sealing ritual is our only chance to fight back.',
        'The seven-day sealing ritual is our only chance to fight back','e27-3'),
    'e27-1':('Irina will return.',70.133,71.533,
        'Irina will return. You must be ready.', 'You must be ready','e27-2')}


def phrase_span(segments,phrase,lower,upper):
    words=[w for s in segments for w in s.get('words',[])];flat=[];owners=[];previous=-math.inf
    for i,w in enumerate(words):
        if not (math.isfinite(w['start']) and math.isfinite(w['end']) and previous<=w['start']<=w['end']
                and 0<=w['probability']<=1):raise ValueError('Invalid reconstruction word evidence')
        previous=w['end']
        tokens=reading_tokens(w['word']);flat.extend(tokens);owners.extend([i]*len(tokens))
    wanted=reading_tokens(phrase)
    for i in range(len(flat)-len(wanted)+1):
        if flat[i:i+len(wanted)]!=wanted:continue
        selected=words[owners[i]:owners[i+len(wanted)-1]+1]
        if (selected[0]['start']<lower-1e-6 or selected[-1]['end']>upper+1e-6
                or any(w['probability']<.35 for w in selected)
                or sum(w['probability'] for w in selected)/len(selected)<.65):continue
        return selected
    raise ValueError('Complete independent phrase missing inside its dialogue boundary')


def reconstruct(rows,evidence,reference,review_sha):
    by={r['id']:r for r in rows};result={}
    board=' '.join(e['storyboard'] for e in reference['entries']);board_tokens=reading_tokens(board)
    for cue_id,(original,start,end,reading,phrase,next_id) in SPECS.items():
        row=by[cue_id]
        if row['text']!=original or row['start']!=start or row['end']!=end:
            raise ValueError('Original reconstruction caption changed')
        index=rows.index(row)
        if index+1>=len(rows) or rows[index+1]['id']!=next_id:raise ValueError('Adjacent original dialogue changed')
        words=reading_tokens(reading)
        if not any(board_tokens[i:i+len(words)]==words for i in range(len(board_tokens)-len(words)+1)):
            raise ValueError('Current final storyboard does not support this reconstruction')
        source=evidence['e27-2' if cue_id=='e27-1' else cue_id]
        if set(source['models'])!={'small.en','medium.en'}:raise ValueError('Both independent ASR records required')
        spans={};variants={}
        for model,record in source['models'].items():
            if record.get('source_review_sha256')!=review_sha:raise ValueError('ASR belongs to a different disputed-source review')
            protected={'not','no','never','cannot','can','could','would','should','must','will','shall',
                       'zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve',
                       'thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty'}
            for segments in (record['segments'],record.get('baseline_segments',[])):
                heard=Counter(t for s in segments for w in s.get('words',[])
                    if w['probability']>=.5 and start-.1<=(w['start']+w['end'])/2<=end+.1
                    for t in reading_tokens(w['word']) if t in protected or t.isdigit())
                if heard-Counter(words):raise ValueError('Editorial reconstruction omitted a protected source word')
            spans[model]=phrase_span(record['segments'],phrase,start-.35,by[next_id]['start']-.1)
            if cue_id=='e27-12':phrase_span(record['segments'],'cursed power',start-.35,by[next_id]['start']-.1)
            variants[model]={'segments':record['segments'],'evidence_sha256':record['evidence_sha256']}
        result[cue_id]={'original_subtitle_text':original,'editorial_reading':reading,
            'source_basis':'original_caption_and_two_ASR_editorial_reconstruction',
            'verified_added_phrase':phrase,'phrase_word_evidence':spans,'complete_asr_records':variants,
            'human_listened':False,'source_speaker_verified':False,
            'note':'Original caption/timecodes retained. Prefix repetition/name variants are not claimed as word-for-word confirmed.'}
    return result
