"""Source-bound episode speech plans and reusable paid audio; no implicit cloning."""
import argparse
import copy
import re
from pathlib import Path
import sys

import generate_monte_episode01 as speech
import fit_render_monte_episode01 as fitting
import prepare_review_editorial_queue as editorial
import prepare_review_episode_editorial as text
from cartesia_pilot import speech_request as cartesia_request
from dub_episode import digest
from process_lock import process_lock
from translate import read_json,save_json,fingerprint
from pipeline_voice import voice_result


def normalized(value):
    return ' '.join(re.sub(r'(^|\n)\s*[—–-]\s*',' ',value).split())


def checked_units(rows,candidate,decision):
    source={r['id']:r for r in rows};translated={r['id']:r for r in candidate['cues']}
    holds={h['cue_id']:h['reason'] for h in decision['holds']}
    if len(holds)!=len(decision['holds']) or not set(holds)<=set(source) or any(not r.strip() for r in holds.values()):
        raise ValueError('Explicit unique source holds required')
    units=decision['units'];seen=set();covered={key:[] for key in source};previous=-1
    if not 1<=len(units)<=512:raise ValueError('Finite nonempty speech scope required')
    for unit in units:
        cue=unit['cue_id'];start,end=unit['start'],unit['end']
        if (unit['id'] in seen or cue not in source or cue in holds or unit['role']=='unknown'
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,60}',unit['role'])
            or type(start) not in (int,float) or type(end) not in (int,float)
            or unit['emotion'] not in ('happy','sad','angry','fearful','disgusted','surprised','calm','fluent','whisper','auto')
            or not unit['translation'].strip() or not unit['evidence'].strip()
            or unit['delivery_mode'] not in ('dialogue','narration')
            or not source[cue]['start']-.001<=start<end<=source[cue]['end']+.001 or start<previous-.001):
            raise ValueError('Unit identity, explicit casting, source window, or chronological coverage differs')
        previous=end;seen.add(unit['id']);covered[cue].append(unit['translation'])
    for cue in source:
        if cue in holds:continue
        if not covered[cue] or not translated[cue]['translation'].strip():
            raise ValueError('Every unresolved or unspoken cue requires an explicit hold')
        if normalized(' '.join(covered[cue]))!=normalized(translated[cue]['translation']):
            raise ValueError('Spoken parts do not cover the frozen cue text exactly')
    return units,holds


def voice_bank(project,roles,inputs):
    bank={}
    if project==100:
        import create_monte_voice_bank as original
        proposal,fp=original.approved_inputs();path=original.ROOT/'voice-bank.private.json';saved=read_json(path)
        for role in roles & set(saved['voices']):
            original.check_cached_role(role,original.source_basis(role,fp),saved)
            bank[role]={'voice_id':saved['voices'][role]['voice_id'],'platform':'minimax'}
        inputs[str(path)]=digest(path)
    root=Path(f'output/review-project-{project}/pipeline-voices-20261031');path=root/'voice-bank.private.json'
    extra=read_json(path) if path.exists() else {'project_id':project,'voices':{}}
    if extra['project_id']!=project:raise ValueError('Role bank scope changed')
    for role in roles-set(bank):
        value=extra['voices'].get(role)
        if value is None:raise ValueError(f'Reusable role voice not yet ready: {role}')
        folder=root/role;receipt=folder/'clone.private.json';payload=folder/'clone-request.private.json'
        if (digest(receipt)!=value['clone_receipt_sha256'] or digest(payload)!=value['request_sha256']
            or voice_result(read_json(receipt),project,role,value['platform'])!=value['voice_id']
            or read_json(folder/'clone-input.private.json')!=value['basis']
            or digest(folder/'reference.wav')!=value['basis']['reference_sha256']):
            raise ValueError('Reusable voice differs from clone/reference receipts')
        bank[role]={'voice_id':value['voice_id'],'platform':value['platform']}
        for item in (receipt,payload,folder/'clone-input.private.json',folder/'reference.wav'):
            inputs[str(item)]=digest(item)
    return bank


def build(decision_path):
    decision=read_json(decision_path);project,episode=decision['project_id'],decision['episode']
    if type(project) is not int or project not in editorial.COUNTS or type(episode) is not int or not 1<=episode<=editorial.COUNTS[project]:raise ValueError('Unknown episode scope')
    folder=editorial.folder_for(project,episode);baseline=editorial.validate_saved(project,episode,folder)
    context=read_json(folder/'source-input.private.json');result=read_json(folder/'editorial-result.private.json')
    if (decision['baseline_result_sha256']!=baseline['result_sha256']
        or decision['source_input_sha256']!=digest(folder/'source-input.private.json')
        or decision['production_casting_candidates_approved'] is not True
        or digest(decision['audit_report_path'])!=decision['audit_report_sha256']):
        raise ValueError('Actual source and reviewed production decisions required')
    candidate=copy.deepcopy(result['candidate'])
    inputs={str(p):digest(p) for p in (decision_path,folder/'source-input.private.json',folder/'editorial-result.private.json',folder/'pt-BR-candidate.srt',Path(decision['audit_report_path']))}
    production=decision.get('production_candidate_path')
    if production:
        from export_review_editorial_edits import apply_edits
        edited=read_json(production);plan_path=Path(decision['production_edit_plan_path']);edit_plan=read_json(plan_path)
        expected=apply_edits(context['timed_source'],candidate,edit_plan['edits'])
        if (edited['baseline_result_sha256']!=baseline['result_sha256'] or edited['candidate']!=expected
            or edited['edit_plan_sha256']!=digest(plan_path) or edited['source_input_sha256']!=decision['source_input_sha256']
            or digest(edit_plan['audit_report_path'])!=edited['audit_report_sha256']):raise ValueError('Production edit chain differs')
        candidate=expected
        inputs.update({production:digest(production),str(plan_path):digest(plan_path)})
    text.validate(candidate,context['timed_source'],context)
    units,holds=checked_units(context['timed_source'],candidate,decision)
    media_path=Path(decision['media_receipt_path']);media=read_json(media_path)
    if (media['source']['project_id']!=project or media['source']['episode']!=episode
        or digest(media['source']['video'])!=media['source']['video_sha256']
        or any(digest(p)!=h for p,h in media['output_sha256'].items())):raise ValueError('Media source changed')
    inputs[str(media_path)]=digest(media_path)
    for p,sha in {media['source']['video']:media['source']['video_sha256'],**media['output_sha256']}.items():inputs[p]=sha
    bank=voice_bank(project,{u['role'] for u in units},inputs)
    groups=[]
    by_id={u['id']:u for u in units};order=[]
    for index,ids in enumerate(decision.get('groups',[[u['id']] for u in units]),1):
        rows=[by_id[i] for i in ids]
        if (not rows or len({(r['role'],r['delivery_mode'],r['emotion']) for r in rows})!=1):raise ValueError('Mixed role/mode/acting group')
        order.extend(ids);voice=bank[rows[0]['role']];spoken=' '.join(r['translation'] for r in rows)
        request=(cartesia_request(spoken,voice['voice_id'],project) if voice['platform']=='cartesia' else
                 {'projectId':project,'model':'speech-2.8-hd','text':spoken,'voiceId':voice['voice_id'],
                  'languageBoost':'Portuguese','format':'wav','speed':1.0,'vol':1.0,'pitch':0,
                  'emotion':rows[0]['emotion'],'duration':None,'language':None,'outputFormat':None,'prompt':None,'referenceVideoList':[]})
        groups.append({'id':f'p{project}-e{episode:02d}-g{index:03d}','role':rows[0]['role'],
                       'delivery_mode':rows[0]['delivery_mode'],'cue_ids':list(dict.fromkeys(r['cue_id'] for r in rows)),
                       'unit_ids':ids,'text':spoken,'start':rows[0]['start'],'end':rows[-1]['end'],
                       'request':request,'cache_key':speech.request_key(request)})
    if order!=[u['id'] for u in units]:raise ValueError('Group order or coverage changed')
    return {'project_id':project,'episode':episode,'groups':groups,'inputs_sha256':inputs,
            'production_cues':[{'id':r['id'],'start':r['start'],'end':r['end'],'translation':c['translation']} for r,c in zip(context['timed_source'],candidate['cues'])],
            'holds':[{'cue_id':key,'reason':value} for key,value in holds.items()],
            'media':{'video':media['source']['video'],'background':media['background']['path']},
            'max_new_tts':len({g['cache_key'] for g in groups}),'new_clone_count':0,
            'native_listening_passed':False,'speaker_audio_verified':False,
            'subtitle_text':text.candidate_srt(context['timed_source'],candidate).decode('utf-8')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision',type=Path,required=True);parser.add_argument('--stage',choices=('prepare','generate','fit'),required=True)
    parser.add_argument('--config',type=Path);parser.add_argument('--ffmpeg',type=Path)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows pipeline production only')
    plan=build(args.decision);project,episode=plan['project_id'],plan['episode']
    root=args.decision.parent/'pipeline-audio-20261031-v1';root.mkdir(exist_ok=True)
    speech.ROOT=root;speech.CACHE=Path(f'output/review-project-{project}/paid-speech-cache');fitting.ROOT=root
    with process_lock(root/'production.lock',timeout=0):
        path=root/'speech-plan.private.json';subtitle=root/'pt-BR-production-candidate.srt'
        if path.exists() and read_json(path)!=plan:raise ValueError('Frozen pipeline plan changed; preserve paid cache and use reviewed revision')
        if not path.exists():save_json(path,plan)
        body=plan['subtitle_text'].encode('utf-8')
        if subtitle.exists() and subtitle.read_bytes()!=body:raise ValueError('Frozen subtitles changed')
        if not subtitle.exists():subtitle.write_bytes(body)
        if args.stage=='prepare':print('PIPELINE_SPEECH_PLAN_READY',project,episode,len(plan['groups']));return
        if args.stage=='generate':
            if not args.config:raise ValueError('Private audio config required')
            with process_lock(Path('output/paid-production.lock'),timeout=0):
                speech.generate(plan,args.config,expected_scope=(project,episode),current_plan_builder=lambda:build(args.decision),max_groups=512)
        else:
            if not args.ffmpeg:raise ValueError('FFmpeg required')
            if plan['holds']:
                save_json(root/'progress.private.json',{'stage':'partial_speech_ready_source_holds','holds':plan['holds']});return
            finished=root/'render-report.private.json'
            if finished.exists():
                report=read_json(finished)
                if report['plan_sha256']!=digest(path) or digest(report['output'])!=report['output_sha256']:raise ValueError('Finished media changed')
                return
            media=(Path(plan['media']['video']),Path(plan['media']['background']))
            fit=fitting.fitted(plan,args.ffmpeg,media)
            if not fit['blocked']:fitting.render(plan,fit,args.ffmpeg,media,f'project{project}_EP{episode:02d}_pt-BR.mp4')


if __name__=='__main__':main()
