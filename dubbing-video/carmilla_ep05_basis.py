"""Limited, versioned EP05 name/idiom normalization with all ASR variants retained."""
from pathlib import Path
from carmilla_ep27_basis import phrase_span
from dub_episode import digest
from translate import read_json
from rerun_carmilla_season import reading_tokens


def reconstruct(rows,evidence,reference,source_audio,review_sha):
    by={r['id']:r for r in rows}
    if (by['e05-7']['text']!='Connor come in my bedroom'
            or by['e05-26']['text']!='leave us your privacy sir'
            or (by['e05-7']['start'],by['e05-7']['end'])!=(16.3,18.733)
            or (by['e05-26']['start'],by['e05-26']['end'])!=(86.4,88.933)):
        raise ValueError('Original EP05 disputed subtitles changed')
    board=' '.join(e['storyboard'] for e in reference['entries'])
    tokens=reading_tokens(board);wanted=reading_tokens('Carmilla come to my bedroom')
    if not any(tokens[i:i+len(wanted)]==wanted for i in range(len(tokens)-len(wanted)+1)):
        raise ValueError('Current storyboard name/invitation evidence missing')
    folder=Path('output/carmilla-source-large-20261019/episode-05/e05-7');inputs={};records={}
    original=by['e05-7'];source_sha=digest(source_audio)
    official_path=Path('output/tools/source-asr-models/large-v3/official-source.json');official=read_json(official_path)
    if official['repo']!='Systran/faster-whisper-large-v3' or official['revision']!='edaa852ec7e145841d8ffdb056a99866b5f0a478':
        raise ValueError('Unexpected pinned model')
    inputs[str(official_path)]=digest(official_path)
    for label,pad in [('context',2.0),('tight',.25)]:
        path=folder/label/'large-v3.json';record=read_json(path);data=record['input'];clip=folder/label/'original.wav'
        if (data['cue']!=original or data['source_audio_sha256']!=source_sha or data['source_review_sha256']!=review_sha
                or data['clip_start']!=max(0,original['start']-pad) or data['clip_end']!=original['end']+pad
                or data['clip_sha256']!=digest(clip) or data['method']!='unprompted-local-large-v3-'+label
                or data['model_revision']!=official['revision'] or data['official_metadata_sha256']!=digest(official_path)
                or data['decoding']!={'language':'en','beam_size':5,'temperature':0,'condition_on_previous_text':False,'word_timestamps':True,'vad_filter':False}
                or record['human_listened'] is not False or record['source_speaker_verified'] is not False):
            raise ValueError('Large model source provenance changed')
        model_root=Path('output/tools/source-asr-models/large-v3')
        if (set(data['model_files'])!={str(model_root/f) for f in ['model.bin','config.json','tokenizer.json','preprocessor_config.json']}
                or data['model_files'][str(model_root/'model.bin')]!='69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1'):
            raise ValueError('Unexpected pinned model files')
        for model_file,sha in data['model_files'].items():
            if digest(Path(model_file))!=sha:raise ValueError('Physical model changed')
            inputs[model_file]=sha
        inputs[str(path)]=digest(path);inputs[str(clip)]=digest(clip)
        records[label]=record
    phrase_span(records['tight']['segments'],'Carmilla come to my bedroom',original['start']-.35,original['end']+.35)
    baseline=Path('output/carmilla-source-verification-20261017/episode-05/e05-7/medium.en.json')
    medium=read_json(baseline)
    if medium['input']['source_review_sha256']!=review_sha:raise ValueError('Medium disputed source review changed')
    phrase_span(medium['segments'],'Camilla come to my bedroom',original['start']-.35,original['end']+.35)
    inputs[str(baseline)]=digest(baseline)
    recons={
        'e05-7':{'original_subtitle_text':original['text'],'editorial_reading':'Carmilla, come to my bedroom!',
            'source_basis':'editorial_name_normalization','large_asr_variants':records,'other_asr_variants':evidence['e05-7'],
            'human_listened':False,'source_speaker_verified':False,
            'note':'Name restored with current storyboard, medium raw and large tight evidence; broad-window disagreement retained, not all-model acoustic agreement.'},
        'e05-26':{'original_subtitle_text':by['e05-26']['text'],'editorial_reading':'Leave us in privacy, sir.',
            'source_basis':'subtitle_semantic_normalization','other_asr_variants':evidence['e05-26'],
            'human_listened':False,'source_speaker_verified':False,
            'note':'Normalize the original request for privacy and sir; not word-for-word original-audio confirmation.'}}
    if set(evidence)!={'e05-7','e05-10','e05-20','e05-26','e05-35'}:raise ValueError('EP05 disputed source scope changed')
    question=by['e05-35'];answer=by['e05-36']
    if (question['text']!='your eyes is do you have fever' or (question['start'],question['end'])!=(111.1,113.7)
            or answer['text']!="no I'll just take a rest" or (answer['start'],answer['end'])!=(114.0,116.4)
            or rows.index(answer)!=rows.index(question)+1):raise ValueError('EP05 exact neighbor captions changed')
    spans={}
    for model,record in evidence['e05-35']['models'].items():
        question_words=phrase_span(record['segments'],'Your eyes do you have a fever',110.75,114.05)
        answer_words=phrase_span(record['segments'],"No I'll just take a rest",113.3,116.75)
        if question_words[-1]['end']>answer_words[0]['start']+1e-6:raise ValueError('Question and answer overlap in ASR')
        core=[w for seg in record['segments'] for w in seg.get('words',[])
              if question['start']<=(w['start']+w['end'])/2<=question['end']]
        if any(w not in question_words+answer_words for w in core):
            raise ValueError('Unassigned core word in the exact EP05 question/answer')
        spans[model]={'question':question_words,'next_answer':answer_words}
    if set(spans)!={'small.en','medium.en'}:raise ValueError('Both full question/answer records required')
    recons['e05-35']={'original_subtitle_text':question['text'],'editorial_reading':'Your eyes! Do you have a fever?',
        'source_basis':'editorial_asr_neighbor_assignment','next_original_caption':answer,
        'question_and_answer_word_evidence':spans,'other_asr_variants':evidence['e05-35'],
        'human_listened':False,'source_speaker_verified':False,
        'note':'Full No answer belongs to next original cue36 and is retained there; ASR onset drift is not a negation in Laura question.'}
    return recons,{c:evidence[c] for c in ['e05-10','e05-20']},inputs


def diary_production_group(rows,old,annotations,reference):
    """Authorize a new reading of one written quote; never identify its original reader."""
    ids=['e05-23','e05-16','e05-17'];by={r['id']:r for r in rows}
    expected=[("my daughter's blood is special",62.566,64.066,'e05-utterance-016'),
              ('It can purify darkness.',64.066,66.033,'e05-utterance-017'),
              ('I sensed it the moment she was born',66.066,68.333,'e05-utterance-018')]
    for cue,(text,start,end,unit_id) in zip(ids,expected):
        row=by[cue];a=annotations[cue]
        if ((row['text'],row['start'],row['end'],old[cue]['id'])!=(text,start,end,unit_id)
                or old[cue]['production_voice']!='Mother' or a['speaker']!='unknown'
                or a.get('speaker_audio_verified') is not False):raise ValueError('Exact diary production source changed')
    if [r['id'] for r in rows[rows.index(by[ids[0]]):rows.index(by[ids[-1]])+1]]!=ids:
        raise ValueError('Written quote source order changed')
    wanted=reading_tokens(' '.join(by[c]['text'] for c in ids))
    board=reading_tokens(' '.join(e['storyboard'] for e in reference['entries']))
    if not any(board[i:i+len(wanted)]==wanted for i in range(len(board)-len(wanted)+1)):
        raise ValueError('Current final storyboard does not contain the complete written quote')
    return {'cue_ids':ids,'original_source_cues':[by[c] for c in ids],
            'original_production_units':[old[c]['id'] for c in ids],
            'production_grouping_policy':'single_written_diary_quote','production_voice':'Mother',
            'source_reader':'unknown','source_speaker_verified':False,'human_listened':False,
            'source_same_reader_confirmed':False,
            'note':'One NEW production reading of a single written diary quote. Storyboard supports the text block, NOT original actor identity.'}
