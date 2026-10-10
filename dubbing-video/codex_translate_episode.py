"""Windows Codex editorial worker; speech/clone APIs remain owned by the renderer."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from dub_episode import digest
from process_lock import process_lock
from translate import fingerprint,read_json,save_json


def response_schema():
    issue={'type':'object','properties':{'severity':{'type':'string','enum':['warning','error']},'reason':{'type':'string'}},'required':['severity','reason'],'additionalProperties':False}
    cue={'type':'object','properties':{'id':{'type':'string'},'translation':{'type':'string'},'speaker':{'type':'string'},'emotion':{'type':'string','enum':['auto','happy','sad','angry','fearful','disgusted','surprised','calm','fluent','whisper']},'script_evidence':{'type':'string'},'review_issues':{'type':'array','items':issue}},'required':['id','translation','speaker','emotion','script_evidence','review_issues'],'additionalProperties':False}
    return {'type':'object','properties':{'matched_main_dialogue':{'type':'boolean'},'match_note':{'type':'string'},'story_notes':{'type':'array','items':{'type':'string'}},'cues':{'type':'array','items':cue}},'required':['matched_main_dialogue','match_note','story_notes','cues'],'additionalProperties':False}


class EditorialReviewRequired(ValueError):
    pass


def validate_response(data,rows,allow_errors=False):
    ids=[r['id'] for r in rows]
    if not data.get('matched_main_dialogue'):raise EditorialReviewRequired('Screenplay cut mismatch requires review')
    if [c['id'] for c in data['cues']]!=ids:raise ValueError('Codex changed, omitted, or reordered cue IDs')
    for cue in data['cues']:
        for key in ('translation','speaker','script_evidence'):
            if not isinstance(cue.get(key),str) or not cue[key].strip():raise ValueError('Missing editorial evidence or translation')
        if not allow_errors and any(i['severity']=='error' for i in cue['review_issues']):
            raise EditorialReviewRequired('Unresolved editorial error; inspect worker output')


def call_codex(exe,prompt,schema,output,log):
    # Native binary avoids a shell and keeps the task prompt exclusively on stdin.
    with log.open('a',encoding='utf-8') as stream:
        result=subprocess.run([str(exe),'-a','never','exec','--sandbox','read-only','--output-schema',str(schema),
                               '--output-last-message',str(output),'-'],input=prompt,text=True,encoding='utf-8',
                              stdout=stream,stderr=stream)
    if result.returncode:raise RuntimeError('Codex editorial run failed; inspect private worker log')
    return read_json(output)


def process_episode(args,episode):
    target=Path(f'output/drama-01/episode-{episode:02d}/editorial')
    if target.exists():
        if all((target/n).exists() for n in ('source.json','translation.json','screenplay-context.json')):return
        raise ValueError('Partial existing editorial directory; inspect instead of overwriting')
    root=Path(f'output/translation-worker/episode-{episode:02d}');root.mkdir(parents=True,exist_ok=True)
    all_rows=read_json(Path('output/drama-01/subtitles/dialogue.en.json'))['segments']
    rows=[r for r in all_rows if r['episode']==str(episode)]
    if not rows:raise ValueError('Episode not found in imported subtitles')
    base=read_json(Path('output/drama-01/episode-01/translation-v2/screenplay-context.json'))
    bible=read_json(args.bible)
    script=args.screenplay.read_text(encoding='utf-8-sig')
    headings=list(re.finditer(r'(?m)^EPISODE (\d+):.*$',script))
    sections={int(h.group(1)):script[h.start():headings[i+1].start() if i+1<len(headings) else len(script)].strip() for i,h in enumerate(headings)}
    if episode not in sections:raise ValueError('Missing matching screenplay episode')
    source=base['sources'][0]
    docx=Path('input/drama-01/screenplay')/source['filename']
    if digest(docx)!=source['sha256']:raise ValueError('Screenplay provenance changed')
    previous=[]
    for n in range(max(1,episode-2),episode):
        for name in ('translation/translated.json','translation-v2/translated.json'):
            p=Path(f'output/drama-01/episode-{n:02d}')/name
            if p.exists():previous.extend(read_json(p)['segments']);break
    context={'episode':episode,'locked_bible':bible,'story_notes':base['story_notes'],
             'full_series_screenplay_path':str(args.screenplay),'screenplay':sections[episode],
             'neighbor_screenplay':{str(n):sections[n] for n in (episode-1,episode+1) if n in sections},
             'timed_source':rows,'previous_translation':previous}
    signature=fingerprint(context);marker=root/'input-fingerprint.json'
    if marker.exists() and read_json(marker)['fingerprint']!=signature:raise ValueError('Editorial inputs changed; inspect checkpoint')
    save_json(marker,{'fingerprint':signature})
    schema=root/'response-schema.json';save_json(schema,response_schema())
    prompt='''You are translating the Carmilla drama into natural Brazilian Portuguese. Read the supplied matched screenplay and timed subtitles; consult the full series screenplay when necessary for continuity. The timed source and cue order are authoritative. Verify major dialogue matches the screenplay; reordered scenes/paraphrases may be compatible, but explain differences. Do not invent absent dialogue or a new character to explain an ASR error. Preserve meaning, negation, relationships, deadlines and locked names/terms. Shorten idiomatically to approach each original time window without dropping meaning. Use script-supported speaker IDs matching prior episodes (Laura, Carmilla, Father, Mother, Irina, Elisabeth); unknown written-note readers stay unknown, never equate author and reader. Cite script evidence per cue, flag ASR/pronoun ambiguity; don't claim audio listening, Brazilian native approval or emotional audio verification. Source-audio verification is unavailable in this text task. Do not call any MCP/clone/TTS/upload API, change code or credentials, or write files yourself. Return only the required structured editorial response. Internally review every line for semantic fidelity and consistency before returning.\n'''+json.dumps(context,ensure_ascii=False)
    draft_path=root/'draft-response.json'
    draft=read_json(draft_path) if draft_path.exists() else call_codex(args.codex_exe,prompt,schema,draft_path,root/'codex.private.log')
    # The second pass must be allowed to repair issues found in the first pass.
    # Only the reviewed result is eligible for publication to the renderer.
    validate_response(draft,rows,allow_errors=True)
    review_path=root/'reviewed-response.json'
    reviewed=read_json(review_path) if review_path.exists() else call_codex(args.codex_exe,
        prompt+'\nReview and correct this candidate carefully. Resolve textual errors; retain uncertainty requiring audio as warnings. Return the complete corrected structured response.\n'+json.dumps(draft,ensure_ascii=False),
        schema,review_path,root/'codex-review.private.log')
    validate_response(reviewed,rows)
    annotations={}
    for row,cue in zip(rows,reviewed['cues']):
        annotations[row['id']]={'source_text':row['text'],'speaker':cue['speaker'],
            'speaker_localized':{'Carmilla':'Camila','Elisabeth':'Elisabete'}.get(cue['speaker'],cue['speaker']),
            'emotion_intent':cue['emotion'],'script_evidence':cue['script_evidence'],
            'speaker_audio_verified':False,'emotion_audio_verified':False}
    screenplay={'schema_version':1,'sources':base['sources'],'story_notes':base['story_notes']+reviewed['story_notes'],
        'episodes':{str(episode):{'match_status':'matched_main_dialogue','match_note':reviewed['match_note'],
                               'script_excerpt':sections[episode],'cue_annotations':annotations}}}
    translation={'episode':str(episode),'revision':1,'source_fingerprint':fingerprint([{k:r[k] for k in ('id','text','start','end')} for r in rows]),
        'screenplay_context_fingerprint':fingerprint(screenplay),'translation_backend':'Windows Codex CLI screenplay translation and separate semantic review',
        'proposed_speech_groups':[],'segments':[{'id':c['id'],'translation':c['translation'],'notes':'Screenplay-informed; original timed source preserved; native listening pending.',
                                              'review_issues':[{'id':c['id'],**i} for i in c['review_issues']]} for c in reviewed['cues']]}
    staged=root/'editorial';staged.mkdir(exist_ok=True)
    for name,value in [('source.json',{'segments':rows}),('screenplay-context.json',screenplay),('translation.json',translation)]:save_json(staged/name,value)
    subprocess.run([sys.executable,'export_translation.py',str(staged/'source.json'),str(staged/'translation.json'),
                    '--screenplay-context',str(staged/'screenplay-context.json'),'--bible',str(args.bible),
                    '--output-dir',str(root/'validated-translation')],check=True)
    # Only a fully validated directory is exposed to the production scanner.
    target.parent.mkdir(parents=True,exist_ok=True);staged.rename(target)
    print('EDITORIAL_READY',episode,len(rows),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--codex-exe',required=True,type=Path);p.add_argument('--start',type=int,default=5);p.add_argument('--end',type=int,default=32)
    p.add_argument('--bible',type=Path,default=Path('output/drama-01/episode-01/translation-v2/series-bible.json'))
    p.add_argument('--screenplay',type=Path,default=Path('input/drama-01/screenplay/Carmilla_Complete_32_Episodes_FINAL.v1.txt'))
    args=p.parse_args()
    if sys.platform!='win32':p.error('Business translation runs on Windows')
    if not args.codex_exe.is_file() or not 1<=args.start<=args.end<=32:p.error('Invalid Codex executable or episode range')
    with process_lock(Path('output/drama-01/translation-worker.lock'),timeout=0):
        progress=Path('output/drama-01/translation-progress.json')
        pending=read_json(progress).get('pending_episodes',[]) if progress.exists() else []
        for episode in range(args.start,args.end+1):
            save_json(progress,{'episode':episode,'stage':'translating','pending_episodes':pending,'updated_at':time.time()})
            try:process_episode(args,episode)
            except EditorialReviewRequired:
                if episode not in pending:pending.append(episode)
                print('EDITORIAL_REVIEW_REQUIRED',episode,'not exposed to production',flush=True)
                continue
            if episode in pending:pending.remove(episode)
        save_json(progress,{'stage':'complete_with_review' if pending else 'complete','pending_episodes':pending,'updated_at':time.time()})


if __name__=='__main__':
    try:main()
    except Exception as exc:
        if isinstance(exc,RuntimeError) and 'translation-worker.lock' in str(exc):raise
        progress=Path('output/drama-01/translation-progress.json')
        previous=read_json(progress) if progress.exists() else {}
        save_json(progress,{**previous,'stage':'stopped','detail':type(exc).__name__,
                  'updated_at':time.time()})
        raise
