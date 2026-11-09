"""Finite reviewed Count repair speech, through existing paid cache and routing gates."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import generate_monte_episode01 as speech
from dub_episode import digest
from process_lock import process_lock
from translate import read_json

ADAPTER={'provider':'mflix-studio','endpoint':'tools/call:generateAudio','api_version':'MCP-2024-11-05'}

FIELDS={'projectId','model','text','voiceId','languageBoost','format','speed','vol','pitch',
        'emotion','duration','language','outputFormat','prompt','referenceVideoList'}


def bound(record):
    path=Path(record['path']);data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('Repair JSON binding changed')
    return json.loads(data.decode('utf-8-sig'))


def routing(plan):
    tool=plan['routing_tool'];folder=Path(tool['path']).parent
    names={'validate_voice_routing.py','validate_delivery.py','validate_episode.py','request_identity.py'}
    if set(tool['files'])!=names or Path(tool['path']).name!='validate_voice_routing.py':raise ValueError('Complete routing checker required')
    for name,h in tool['files'].items():
        if digest(folder/name)!=h:raise ValueError('Routing checker source changed')
    chunks={}
    for item in plan['routing_checks']:
        bound(item);manifest=Path(item['path']);r=subprocess.run([sys.executable,str(tool['path']),str(manifest),'--stage','plan'],capture_output=True,text=True,encoding='utf-8',errors='replace')
        if r.returncode:raise ValueError('Actual voice routing check failed')
        result=json.loads(r.stdout)
        if result.get('status')!='voice_routing_checks_passed' or result.get('pending_checks'):raise ValueError('Voice routing dependencies unresolved')
        # Parse only bound JSON here; the isolated checker already enforces path scope.
        m=read_json(manifest)
        if (m.get('project_key')!='review-100' or m.get('episode_key')!=f"EP{plan['episode']:02d}" or m.get('cut_version')!='comment-repair-20261109'):
            raise ValueError('Routing episode identity differs from production')
        file=m['files']['chunks'];p=manifest.parent/file['path'];c=bound({'path':str(p),'sha256':file['sha256']})
        t=m['files']['turns'];turns={x['id']:x for x in bound({'path':str(manifest.parent/t['path']),'sha256':t['sha256']})['turns']}
        for row in c['chunks']:
            if row['id'] in chunks:raise ValueError('Duplicate routing chunk')
            request=row['request'];p=manifest.parent/request['path'];envelope=bound({'path':str(p),'sha256':request['sha256']})
            chunks[row['id']]={'envelope':envelope,'speaker':row['speaker'],'turn':turns[row['turn_id']]}
    if set(chunks)!={g['id'] for g in plan['groups']}:raise ValueError('Routing coverage differs from actual paid plan')
    baseline=bound(plan['baseline_plan']);known={g['id']:g for g in baseline['groups']}
    for g in plan['groups']:
        check_bridge(g,chunks[g['id']],known[g['source_group_id']])


def check_bridge(group, chunk, original):
    envelope=chunk['envelope'];turn=chunk['turn']
    if any(envelope.get(k)!=v for k,v in ADAPTER.items()):raise ValueError('Routing adapter differs from actual submission')
    if chunk['speaker']!=group['role'] or turn['speaker']!=group['role']:raise ValueError('Routing speaker differs from production role')
    # Scoped source SRT uses original production cue IDs, not renumbered positions.
    if [r['cue_id'] for r in turn['source_refs']]!=original['cue_ids']:raise ValueError('Routing source cues differ from original speech group')
    if speech.request_key(envelope['payload'])!=speech.request_key(group['request']):raise ValueError('Routed request differs from submitted speech')


def validate(path, *, run_routing=True):
    plan=read_json(path)
    if (plan.get('project_id')!=100 or type(plan.get('episode')) is not int or not 1<=plan['episode']<=32
        or plan.get('new_clone_count')!=0 or plan.get('purpose') not in ('review_repair','voice_audition')):raise ValueError('Wrong finite repair scope')
    baseline=bound(plan['baseline_plan']);known={g['id']:g for g in baseline['groups']}
    if (baseline['project_id'],baseline['episode'])!=(100,plan['episode']):raise ValueError('Original episode plan differs')
    matrix=bound(plan['issue_matrix']);comments={r['comment_id']:r for r in matrix['issues']}
    for name,h in plan['inputs_sha256'].items():
        if digest(name)!=h:raise ValueError('Repair source changed')
    groups=plan['groups']
    if not 1<=len(groups)<=128 or len({g['id'] for g in groups})!=len(groups):raise ValueError('Finite unique repair groups required')
    requests={}
    for g in groups:
        original=known.get(g.get('source_group_id'))
        if original is None or original['role']!=g.get('role') or g['role']=='unknown':raise ValueError('Source group speaker differs')
        ids=g.get('comment_ids')
        if not isinstance(ids,list) or not ids or any(i not in comments or plan['episode'] not in comments[i].get('candidate_episodes',[comments[i]['episode']]) for i in ids):raise ValueError('Repair comment scope differs')
        req=g['request']
        if (set(req)!=FIELDS or req['projectId']!=100 or req['model']!='speech-2.8-hd' or req['languageBoost']!='Portuguese'
            or req['format']!='wav' or type(req['voiceId']) is not str or not req['voiceId'].startswith('minimax:')
            or req['text']!=g['text'] or type(req['text']) is not str or not req['text'].strip()
            or req['emotion'] not in ('happy','sad','angry','fearful','disgusted','surprised','calm','auto')
            or any(req[x] is not None for x in ('duration','language','outputFormat','prompt')) or req['referenceVideoList']!=[]):
            raise ValueError('Unsupported actual repair request')
        for key in ('speed','vol','pitch'):
            value=req[key]
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid speech parameter')
        if req['speed']<=0 or req['vol']<=0 or type(req['pitch']) is not int:raise ValueError('Invalid speech settings')
        oldvoice=original['request']['voiceId']
        if req['voiceId']!=oldvoice:
            if plan['purpose']=='voice_audition':
                catalog=bound(plan['voice_catalog'])
                if req['voiceId'] not in {x['voiceId'] for x in catalog['data']}:raise ValueError('Audition voice not in actual catalog')
            else:
                basis=bound(g['cast_basis'])
                if (basis.get('role')!=g['role'] or basis.get('old_voice_id')!=oldvoice or basis.get('new_voice_id')!=req['voiceId']
                    or g['source_group_id'] not in basis.get('group_ids',[]) or basis.get('candidate_selected') is not True):raise ValueError('Unbound voice migration')
        if g['cache_key']!=speech.request_key(req):raise ValueError('Paid request identity differs')
        requests[g['cache_key']]=req
    if plan['max_new_tts']!=len(requests):raise ValueError('New request bound differs')
    if plan['purpose']=='voice_audition' and (len(requests)>2 or len({g['source_group_id'] for g in groups})!=1):raise ValueError('Audition exceeds fixed two-voice single-source test')
    if run_routing:routing(plan)
    return plan


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--config',type=Path);p.add_argument('--check-only',action='store_true');a=p.parse_args()
    if sys.platform!='win32':raise ValueError('Business generation runs on Windows')
    if a.plan.name!='speech-plan.private.json':raise ValueError('Use the canonical frozen repair plan filename')
    plan=validate(a.plan)
    if a.check_only:print('COMMENT_SPEECH_CHECKED',plan['episode'],len(plan['groups']));return
    if a.config is None:raise ValueError('Existing private audio configuration required')
    speech.ROOT=a.plan.parent;speech.CACHE=Path('output/review-project-100/paid-speech-cache')
    with process_lock(speech.ROOT/'production.lock',timeout=0),process_lock(Path('output/paid-production.lock'),timeout=0):
        speech.generate(plan,a.config,expected_scope=(100,plan['episode']),current_plan_builder=lambda:validate(a.plan),max_groups=128)
    print('COMMENT_SPEECH_READY',plan['episode'],len(plan['groups']))


if __name__=='__main__':main()
