"""Finite source-bound revision of Review2808 feedback; existing voices only."""
import argparse
import copy
from pathlib import Path
import re
import sys
from translate import read_json,save_json,fingerprint
from dub_episode import digest
from cartesia_pilot import bind
from clone_feedback_pilot import expected_request
from clone_feedback_v2 import completed
from process_lock import process_lock
import contextual_ptbr_candidate as pipeline
import systematic_ptbr_review as baseline

ROOT=Path('output/feedback-repair-20261028')
SPECS={
 'e05-group-011':('Como?',1.,'surprised'),
 'e05-group-017':('Devia temer, tudo grita pra fugir, mas não dá pra odiar ela. Me sinto segura.',1.05,'surprised'),
 'e26-group-002':('CAMILA!',1.,'fearful'),
 'e26-group-003':('NÃO!',1.,'fearful'),
 'e26-group-004':('Que patético.',.95,'calm'),
 'e26-group-015':('Preciso de tempo mesmo, pra reunir meu exército.',.95,'calm'),
 'e32-group-003':('Você vai virar vampira pra sempre.',1.,'calm'),
 'e32-group-008':('IMPOSSÍVEL!',1.,'fearful'),
 'e32-group-021':('Prometi proteger ela <#0.15#> há quinze anos. Falhei.',1.05,'sad'),
}
EDITS={
 'e05-group-011':{'e05-11':'Como?'},
 'e05-group-017':{'e05-18':'Devia temer, tudo grita pra fugir,','e05-19':'mas não dá pra odiar ela. Me sinto segura.'},
 'e32-group-021':{'e32-25':'Prometi proteger ela há quinze anos.','e32-26':'Falhei.'},
}
POLICY={'max_atempo':1.2,'max_post_gap_seconds':.8,'no_speech_truncation':True,
 'no_paid_retry':True,'new_request_cap':8,'new_clone_count':0}


def clean(text):return re.sub(r'<#\d+(?:\.\d+)?#>','',text)
def words(text):return re.findall(r'\w+',clean(text).casefold())


def build_manifest():
    base=read_json(baseline.ROOT/'manifest.private.json');baseline.validate(base)
    packet=read_json(ROOT/'source-packet.private.json');bank=read_json(pipeline.BANK)['voices']
    comments=read_json('output/review-feedback/2026-10-27/asset-2808-page-1.private.json')
    if len(comments)!=13 or {x['commentId'] for x in comments}!=set(range(8298,8311)):
        raise ValueError('Exact feedback scope required')
    proposal=read_json(ROOT/'editorial-proposal.private.json')
    if proposal!={'specs':{k:list(v) for k,v in SPECS.items()},'cue_edits':EDITS,'policy':POLICY}:
        raise ValueError('Fixed finite reviewed repair scope changed')
    inputs={str(p):digest(p) for p in [baseline.ROOT/'manifest.private.json',ROOT/'source-packet.private.json',
      ROOT/'editorial-proposal.private.json',pipeline.BANK,Path('output/review-feedback/2026-10-27/asset-2808-page-1.private.json')]}
    scenes=[]
    for n in (5,21,26,32):
        e=copy.deepcopy(next(x for x in base['episodes'] if x['episode']==n));folder=Path(e['folder'])
        plan=read_json(folder/'plan.json');context=read_json(folder/'screenplay-context.json');report=read_json(folder/'render-report.json')
        if packet[str(n)]!={'plan':plan,'context':context,'report':report}:raise ValueError('Source packet differs')
        assets=plan['assets']
        paths=[folder/'plan.json',folder/'screenplay-context.json',folder/'render-report.json',folder/'reviewed.json',
          Path(e['subtitle']),Path(e['video'])]+[Path(assets[k]) for k in ('video','bgm','sfx')]
        inputs.update({str(p):digest(p) for p in paths})
        if digest(e['video'])!=e['video_sha256']:raise ValueError('Current delivery changed')
        old={u['id']:u for u in report['utterances']};groups=[];cue_changes={}
        for u in report['utterances']:
            if digest(u['fitted_path'])!=u['fitted_sha256']:raise ValueError('Published audio changed')
            inputs[u['fitted_path']]=u['fitted_sha256']
        for i,source in enumerate(plan['units']):
            uid=source['id']
            if uid not in SPECS:continue
            if source.get('source_speaker') in (None,'unknown'):raise ValueError('Do not newly cast source unknown')
            text,speed,emotion=SPECS[uid];role=source['production_voice']
            if ['speech-2.8-hd',bank[role]['voice_id']] not in base['whole_season_stats']['voice_configuration_by_role'][role]:
                raise ValueError('Only an already-delivered role clone may be used')
            cue_changes.update(EDITS.get(uid,{}))
            caption=' '.join(EDITS[uid][cid] for cid in source['cue_ids']) if uid in EDITS else source['translation']
            if words(caption)!=words(text):raise ValueError('Speakable words and subtitles differ')
            start=old[uid].get('audio_start',source['start'])
            following=old[plan['units'][i+1]['id']].get('audio_start',plan['units'][i+1]['start']) if i+1<len(plan['units']) else e['duration_seconds']
            limit=min(following-.05,e['duration_seconds'],source['end']+.8)
            groups.append({'id':uid,'episode':n,'source_unit_ids':[uid],'source_units':[copy.deepcopy(source)],
              'start':source['start'],'audio_start':start,'end':source['end'],'audio_end_limit':limit,
              'caption':caption,'request':expected_request(role,text,speed,emotion,bank),
              'production_voice':role,'source_speaker':source['source_speaker'],'emotion_direction':emotion,'unknown_retained':False})
        scene={'id':f'F{len(scenes)+1}','episode':n,'start':0.,'end':e['duration_seconds'],'base':e,
          'assets':assets,'source_report':report,'groups':groups,'cue_changes':cue_changes}
        if n==21:
            scene.update(dialogue_gains={'e21-group-005':10**(3/20)},
              bgm_filter="volume='1-0.5*max(0,min(1,min((t-24.383)/0.25,(29.979-t)/0.25)))':eval=frame")
        scenes.append(scene)
    if len([g for s in scenes for g in s['groups']])!=9:raise ValueError('Expected nine fixed synthesis requests')
    note=('针对基线2808的13条评审制作的新候选；F1第05集/F2第21集/F3第26集/F4第32集，A现有交付/B候选。'
      '复用已有角色MiniMax音色；部分Laura/Carmilla从Cartesia改为其已有MiniMax音色，需审核音色连续性。'
      '最多8次新TTS、0新增克隆；Como复用既有正确拼写候选，非已验收。其余发音候选采用完整句、正确拼写和明确情绪/语速控制，无中文谐音/IPA。'
      '第21集木匠目标对白+3dB，背景音乐局部平滑降低约6dB，音效保留。字幕同步口语措辞及Como标点，原始文件不覆盖。'
      '尚未解决：EP01 para与EP05 trevas的原说话者unknown，保留现有录音；EP32开场对白与画面的错位正在核原声，不交换角色或猜测移动。'
      '这不是13条全部修复通过；所有巴葡发音、喊叫、节奏、音色仍须母语听审。未评论不算验收。')
    return {'feedback_revision':True,'project_id':59,'review_project_id':148,'scenes':scenes,'inputs':inputs,
      'translation_changes':EDITS,'timing_policy':POLICY,'paid_request_cap':8,'new_clone_count':0,'native_listening_passed':False,
      'comment_ids':list(range(8298,8311)),'publication_note':note,
      'unresolved':['EP01 para: source identity unknown; published recording retained',
        'EP05 trevas: source identity unknown; published recording retained',
        'EP32 opening timing: source/picture crosscheck required; no speaker swapping or guessed placement']}


def preflight(m):
    requests={fingerprint(g['request']):g['request'] for g in pipeline.known_groups(m)}
    aliases={a:(k,v) for k,r in requests.items() for a,v in pipeline.numeric_request_variants(r).items()}
    selected={};receipt_requests={};matches={k:[] for k in requests}
    for p in Path('output').rglob('*.submission-pending.json'):
        a=p.with_name(p.name.removesuffix('.submission-pending.json')+'.json')
        if not a.exists() or not isinstance(read_json(a),dict) or not read_json(a).get('taskId'):
            raise ValueError('Unknown historical submission; reconcile before any new generation')
    for marker in Path('output').rglob('request-fingerprint.json'):
        a=read_json(marker).get('fingerprint')
        if a in aliases:
            k,v=aliases[a];matches[k].append((marker.parent,v))
    for k,r in requests.items():
        completed_matches=[];incomplete=[]
        for p,v in matches[k]:
            if (p/'audio-receipt.json').exists():completed(p,v);completed_matches.append((p,v))
            else:incomplete.append((p,v))
        if incomplete:
            # Only our exact accepted request may resume polling. Never bypass old partial work.
            if len(incomplete)!=1 or incomplete[0][0]!=ROOT/'requests'/k or completed_matches:
                raise ValueError('Incomplete older matching request requires reconciliation')
            p,v=incomplete[0]
        elif completed_matches:p,v=sorted(completed_matches,key=lambda x:str(x[0]))[0]
        else:p,v=ROOT/'requests'/k,r
        selected[k]=p;receipt_requests[k]=v
    new=sum(not (p/'audio-receipt.json').exists() for p in selected.values())
    if new>m['paid_request_cap']:raise ValueError('Finite new-request cap exceeded before MCP initialization')
    save_json(ROOT/'cache-preflight.private.json',{'selected':{k:str(v) for k,v in selected.items()},
      'receipt_requests':receipt_requests,'unique_request_count':len(requests),'completed_exact_matches':len(requests)-new,
      'max_new_requests':new,'new_clone_count':0})
    return selected


def configure():
    pipeline.ROOT=ROOT;pipeline.TIMING_REVISION=True;pipeline.MAX_NEW_REQUESTS=8
    pipeline.build_manifest=build_manifest;pipeline.preflight=preflight


def brief_paragraphs(m,chapters,audio,fitted,differences):
    paragraphs=['Carmilla — Feedback 2026-10-28 / Candidata A-B v1',m['publication_note'],
      'A = entrega atual; B = candidata, ainda sem aprovação de pronúncia/interpretação por nativo.',
      'EP32 timing is unresolved in this revision; do not interpret unchanged opening timing as a fix.',
      'Two source-unknown pronunciations remain open; voice casting is not silently inferred.',
      'Emotion labels/capitalization are production controls, not proof of successful screams.',
      'Pronunciation trials at sentence level are hypotheses; no automatic model training or guaranteed accent correction.',
      'Post atempo<=1.2; synthesis speed is separately listed. Nominal combined rate may exceed1.2. No speech cuts.',
      'Review complete context including unreported words; report F1-F4+A/B+time+phrase. No private recording required.']
    for c in chapters:paragraphs.append(f'{c["scene_id"]}{c["label"]} | EP{c["episode"]:02} | reel {c["reel_start"]:.3f}–{c["reel_end"]:.3f}s')
    for s in m['scenes']:
        for u in s['groups']:
            req=u['request'];f=fitted[u['id']];a=audio[fingerprint(req)]
            paragraphs += [f'{u["id"]} | EP{u["episode"]:02} {u["start"]:.3f}s | role {u["production_voice"]}; source document identity {u["source_speaker"]}',
              f'EN: {u["source_units"][0]["source_text"]}',f'A: {u["source_units"][0]["translation"]}',f'B: {u["caption"]}',
              f'Synthesis speed {req["speed"]}; post atempo {f["atempo_factor"]:.4f}; nominal combined {req["speed"]*f["atempo_factor"]:.4f}; emotion direction {u["emotion_direction"]}; reused paid audio {a["reused_completed_audio"]}.']
    paragraphs+=['Unresolved: '+x for x in m['unresolved']]
    for d in differences:paragraphs.append(f'ASR lead only (not confirmed error): {d["unit_id"]} target {d["expected_text"]} / ASR {d["asr_transcript"]}')
    return paragraphs


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',required=True,choices=['prepare','preflight','generate','fit','screen','render','publish'])
    p.add_argument('--ffmpeg',type=Path);p.add_argument('--mcp-config',type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Run material processing on Windows')
    configure();ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/('screening.lock' if a.stage=='screen' else 'pipeline.lock'),timeout=0):
        if a.stage=='prepare':
            m=build_manifest();path=ROOT/'manifest.private.json'
            if path.exists() and read_json(path)!=m:raise ValueError('Do not overwrite another paid scope')
            bind(ROOT/'manifest-fingerprint.json',m)
            if not path.exists():save_json(path,m)
            pipeline.validate(m,False)
            from contextual_ptbr_render import subtitle_rows
            for s in m['scenes']:subtitle_rows(s)
            print('FEEDBACK_PREPARED',fingerprint(m),flush=True);return
        m=read_json(ROOT/'manifest.private.json');pipeline.validate(m)
        if a.stage=='preflight':preflight(m);print('FEEDBACK_PREFLIGHT_OK',flush=True)
        elif a.stage=='generate':
            with process_lock(Path('output/paid-production.lock'),timeout=0):pipeline.synthesize(m,a.mcp_config,a.ffmpeg)
        elif a.stage=='fit':pipeline.fit(m,a.ffmpeg)
        elif a.stage=='screen':pipeline.screen(m,a.ffmpeg)
        elif a.stage=='render':
            from contextual_ptbr_render import render
            render(m,a.ffmpeg)
        else:
            approval=read_json(ROOT/'media-approval.private.json');r=read_json(ROOT/'render-report.private.json')
            if (approval['status']!='independent_media_pass' or approval['render_sha256']!=digest(ROOT/'render-report.private.json')
              or digest(approval['report_path'])!=approval['report_sha256']):raise ValueError('Actual final media approval required')
            from contextual_ptbr_render import publish
            publish(m,a.mcp_config)


if __name__=='__main__':main()
