"""Whole-season traceability and a zero-TTS contextual evaluation baseline."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
import subprocess
import sys
import time
import hashlib

from translate import read_json, save_json, fingerprint
from dub_episode import digest, probe
from cartesia_pilot import bind
from process_lock import process_lock
from publish_season_candidates import candidates, PUBLICATION
from resume_season_publication import retained_delivery
from publish_review import document, materials, register, check_matches
from notify_season_complete import verify_delivery
from mflix_client import Mflix

ROOT=Path('output/ptbr-systematic-baseline-20261024')
SELECTED=(1,5,17,21,26,32)
RULES=[
 ('meaning','Sentido e contexto','Preservar negação, relações, agente, intenção e informação do enredo; conferir roteiro e legendas da versão correta.'),
 ('time','Prazos e quantidades','Conferir prazos, números e sequência dos acontecimentos; não omitir para caber no tempo.'),
 ('names','Nomes e termos','Consistência de nomes, identidades, parentesco e termos; distinguir nomes usados como disfarce.'),
 ('register','Diálogo brasileiro','Naturalidade oral e registro do personagem; avaliar frases completas e continuidade entre legendas.'),
 ('pronunciation','Pronúncia brasileira geral','Identificar palavras com sotaque estrangeiro; localizar a frase antes de inferir a causa fonética.'),
 ('vowels','Vogais e nasalização','Ouvir vogais abertas/fechadas, nasais e ditongos; não reduzir a avaliação a palavras já comentadas.'),
 ('consonants','Consoantes','Ouvir articulação, encontros consonantais, lh/nh e sons de r/s; respeitar variação regional brasileira.'),
 ('prosody','Acento e ritmo','Ouvir sílaba tônica, finais átonos, ligação entre palavras e pausas dentro do grupo de sentido.'),
 ('acting','Interpretação','Comparar intenção, medo, pedido, raiva, surpresa e fala íntima com imagem, contexto e interpretação original.'),
 ('identity','Identidade vocal','Mesmo personagem ao longo dos episódios; avaliar naturalidade, semelhança e mudanças de timbre separadamente.'),
 ('alignment','Tempo e turnos','Verificar início/fim de fala, aceleração, sobreposição e preservação de todas as palavras.'),
 ('mix','Mixagem','Inteligibilidade, música, efeitos, ruído e voz residual em inglês; localizar a faixa antes de atribuir causa.'),
 ('acceptance','Aceitação explícita','Marcar Aceitável / Ajustar / Não avaliado por dimensão; ausência de comentário não é aprovação.'),
]
# Orthographic screening only: these are candidate occurrences, not pronunciation errors.
PATTERNS={
 'nasal_spelling':r'\b\w*[ãõ]\w*\b',
 'unstressed_final_vowel_candidates':r'\b\w{2,}[eo]\b',
 'lh_nh_candidates':r'\b\w*(?:lh|nh)\w*\b',
 'r_s_candidates':r'\b\w*[rs]\w*\b',
 'negation_candidates':r'\b(?:não|nunca|ninguém|nenhum|nenhuma|nem|sem)\b',
 'time_number_candidates':r'\b(?:dias?|anos?|horas?|noites?|amanhã|hoje|sete|quinze|dois|duas|três)\b',
}


def inventory(ffmpeg):
    available=candidates()
    if set(available)!=set(range(1,33)):raise ValueError('Need all actual 32 episode deliveries')
    inputs={};episodes=[];role_counts=Counter();emotions=Counter();voice_ids=defaultdict(set)
    for n,folder in sorted(available.items()):
        plan=read_json(folder/'plan.json');report=read_json(folder/'render-report.json')
        receipt_path=PUBLICATION/f'episode-{n:02}'/report['output_sha256']/'publication-result.json'
        receipt=read_json(receipt_path)
        retained_delivery(n,folder,receipt,receipt,receipt_path.parent/'candidate.json')
        subtitle=folder/f'Carmilla_EP{n:02}_pt-BR_revised.srt'
        video=Path(report['output'])
        if digest(video)!=report['output_sha256']:raise ValueError('Delivered video bytes changed')
        duration=float(probe(video,ffmpeg)['format']['duration'])
        for path in [folder/'plan.json',folder/'reviewed.json',folder/'screenplay-context.json',
          folder/'render-report.json',subtitle,receipt_path,receipt_path.parent/'candidate.json']:
            inputs[str(path)]=digest(path)
        if len(plan['units'])!=len(report['utterances']):raise ValueError('Rendered unit count differs')
        units=[]
        for u,r in zip(plan['units'],report['utterances']):
            if any(r.get(k)!=v for k,v in u.items()):raise ValueError('Current audio and reviewed wording differ')
            if r['atempo_factor']>1.200001:raise ValueError('Unapproved production acceleration')
            role_counts[u['production_voice']]+=1;emotions[u['emotion']]+=1
            req=r.get('request',{});voice_ids[u['production_voice']].add((req.get('model'),req.get('voiceId')))
            text=u['translation']
            units.append({**u,'request':req,'atempo_factor':r['atempo_factor'],
              'screening_candidates':{key:re.findall(pattern,text,re.I) for key,pattern in PATTERNS.items()},
              'native_approval':'not_established'})
        episodes.append({'episode':n,'folder':str(folder),'video':str(video),'video_sha256':report['output_sha256'],
          'subtitle':str(subtitle),'subtitle_sha256':digest(subtitle),'duration_seconds':duration,
          'video_asset_id':receipt['asset_id'],'version':receipt['version'],'url':receipt['url'],
          'subtitle_asset_id':receipt['subtitle_asset_id'],
          'subtitle_cue_count':len(re.findall(r'(?m)^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->',subtitle.read_text(encoding='utf-8-sig'))),
          'units':units})
    for path in [Path('output/review-feedback/2026-10-21/comments-all.private.json'),
      Path('output/review-feedback/2026-10-24/asset-2731-page-1.private.json')]:inputs[str(path)]=digest(path)
    archived=read_json('output/review-feedback/2026-10-21/comments-all.private.json')
    acting={7698,7702,7706,7809,7808,7811,7820,7819};mix={7802,7804,7805,7821,7822}
    feedback=[]
    for row in archived['results']:
        for comment in row['comments']:
            cid=comment['commentId'];categories=[]
            if cid in acting:categories.append('acting')
            if cid in mix:categories.append('mix')
            if cid==7807:categories.append('prosody')
            if cid==7823:categories.append('identity')
            if not categories or cid==7811:categories.append('pronunciation')
            feedback.append({'comment_id':cid,'episode':row['episode'],'asset_id':row['material']['assetId'],
              'content':comment['content'],'checklist_categories':categories,
              'classification':'analyst routing, not confirmed acoustic root cause','location':'Quoted phrase/time evidence only; unconfirmed otherwise'})
    for comment in read_json('output/review-feedback/2026-10-24/asset-2731-page-1.private.json')['data']:
        feedback.append({'comment_id':comment['commentId'],'episode':None,'asset_id':2731,'content':comment['content'],
          'checklist_categories':['pronunciation'],'classification':'analyst routing, not confirmed acoustic root cause',
          'location':'Ambiguous between two existing B candidates, no exact timestamp'})
    if len({c['comment_id'] for c in feedback})!=len(feedback):raise ValueError('Keep distinct comment IDs; no duplicate snapshot merge')
    by_n={r['episode']:r for r in episodes};chapters=[]
    for i,n in enumerate(SELECTED,1):
        e=by_n[n]
        chapters.append({'id':f'S{i:02}','episode':n,'source_start':0,'source_end':e['duration_seconds'],
          'selection':'Complete episode, targeted baseline; not random or blind acceptance testing',
          'production_roles':sorted({u['production_voice'] for u in e['units']}),
          'direction_emotions':sorted({u['emotion'] for u in e['units']}),
          'source_unknown_unit_ids':[u['id'] for u in e['units'] if u.get('source_speaker','unknown')=='unknown']})
    return {'schema_version':1,'episodes':episodes,'chapters':chapters,'inputs':inputs,'rules':RULES,'feedback':feedback,
      'coverage_limits':['Targeted six-episode baseline, not a full phoneme inventory or statistical quality estimate.',
        'Known curtain/background-noise feedback in EP12/13/31 is outside this reel; full episode URLs and comment IDs remain in inventory/brief.',
        'No feedback on semantics does not prove translation accuracy. All dimensions require explicit review.'],
      'screening_policy':'All text matches are inspection candidates, not acoustic error findings or native approval',
      'whole_season_stats':{'episode_count':32,'unit_count':sum(len(e['units']) for e in episodes),
        'subtitle_cue_count':sum(e['subtitle_cue_count'] for e in episodes),'feedback_comment_count':len(feedback),
        'production_role_units':dict(role_counts),'direction_emotion_units':dict(emotions),
        'voice_configuration_by_role':{k:[list(x) for x in sorted(v,key=str)] for k,v in voice_ids.items()},
        'source_unknown_units':sum(u.get('source_speaker','unknown')=='unknown' for e in episodes for u in e['units'])},
      'policy':'Current delivered baseline; no translation edits, no TTS, no cloning, no claimed new pronunciation improvement.'}


def validate(m):
    if len(m['episodes'])!=32 or [c['episode'] for c in m['chapters']]!=list(SELECTED):raise ValueError('Baseline scope differs')
    if m['rules']!=[list(r) for r in RULES] or len(m['chapters'])!=6:raise ValueError('Rules differ')
    if read_json(ROOT/'manifest-fingerprint.json')['fingerprint']!=fingerprint(m):raise ValueError('Baseline manifest changed')
    for p,sha in m['inputs'].items():
        if digest(p)!=sha:raise ValueError('Bound original evidence changed')
    for e in m['episodes']:
        if e['episode'] in SELECTED and digest(e['video'])!=e['video_sha256']:raise ValueError('Selected original video changed')


def prepare(ffmpeg):
    m=inventory(ffmpeg);path=ROOT/'manifest.private.json'
    if path.exists() and fingerprint(read_json(path))!=fingerprint(m):raise ValueError('Existing baseline manifest differs')
    bind(ROOT/'manifest-fingerprint.json',m)
    if not path.exists():save_json(path,m)
    validate(read_json(path));print('SYSTEMATIC_BASELINE_PREPARED',m['whole_season_stats']['unit_count'],flush=True)


def audio_payload(path,ffmpeg):
    p=subprocess.run([str(ffmpeg),'-v','error','-i',str(Path(path).resolve()),'-map','0:a:0',
      '-c:a','copy','-f','hash','-hash','sha256','-'],check=True,capture_output=True,text=True)
    return p.stdout.strip()


def render(m,ffmpeg):
    validate(m);result=ROOT/'render-report.private.json';out=ROOT/'Carmilla_ptBR_systematic_CURRENT_BASELINE_v1.mp4'
    if result.exists():
        r=read_json(result)
        if r['manifest_sha256']!=digest(ROOT/'manifest.private.json') or r['output_sha256']!=digest(out):raise ValueError('Existing baseline reel changed')
        brief=ROOT/'brief-report.private.json'
        if not brief.exists():write_brief(m,r)
        else:
            b=read_json(brief)
            if digest(b['path'])!=b['sha256'] or b['render_report_sha256']!=digest(result):raise ValueError('Existing brief changed')
        print('SYSTEMATIC_REEL_REUSED',flush=True);return
    clips=ROOT/'chapters';clips.mkdir(exist_ok=True);rows=[];cursor=0.
    for c in m['chapters']:
        e=next(e for e in m['episodes'] if e['episode']==c['episode'])
        # Copy the exact final SRT into this isolated directory; original remains untouched.
        srt=clips/f'{c["id"]}.srt';srt.write_bytes(Path(e['subtitle']).read_bytes())
        label=f'{c["id"]} | EP{e["episode"]:02} | CURRENT BASELINE - NOT NEW REPAIR'
        clip=clips/f'{c["id"]}.mp4'
        vf=(f'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,'
          f'setsar=1,fps=25,subtitles={srt.name}:force_style=\'Fontsize=18,MarginV=35\','
          f'drawbox=x=0:y=0:w=iw:h=55:color=black@0.8:t=fill,'
          f'drawtext=text=\'{label}\':fontcolor=white:fontsize=19:x=(w-tw)/2:y=18')
        subprocess.run([str(ffmpeg),'-v','error','-y','-i',str(Path(e['video']).resolve()),'-map','0:v:0','-map','0:a:0',
          '-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','copy',
          '-movflags','+faststart',clip.name],cwd=clips,check=True,capture_output=True)
        original_audio=audio_payload(e['video'],ffmpeg)
        if audio_payload(clip,ffmpeg)!=original_audio:raise ValueError('Baseline audio payload changed')
        duration=float(probe(clip,ffmpeg)['format']['duration'])
        rows.append({**c,'path':str(clip),'sha256':digest(clip),'subtitle_sha256':digest(srt),
          'source_video_sha256':e['video_sha256'],'audio_payload_hash':original_audio,
          'reel_start_seconds':cursor,'reel_end_seconds':cursor+duration,
          'rendered_duration_seconds':duration})
        cursor+=duration;print('SYSTEMATIC_CHAPTER_READY',c['id'],round(duration,3),flush=True)
    listing=clips/'concat.txt';listing.write_text(''.join(f"file '{Path(c['path']).name}'\n" for c in rows),encoding='utf-8')
    subprocess.run([str(ffmpeg),'-v','error','-y','-f','concat','-safe','0','-i',str(listing.resolve()),'-c','copy','-movflags','+faststart',str(out.resolve())],check=True,capture_output=True)
    r={'output':str(out),'output_sha256':digest(out),'manifest_sha256':digest(ROOT/'manifest.private.json'),
      'chapters':rows,'duration_seconds':float(probe(out,ffmpeg)['format']['duration']),
      'new_tts_count':0,'new_clone_count':0,'native_listening_passed':False,'kind':'existing_delivery_baseline'}
    save_json(result,r);write_brief(m,r);print('SYSTEMATIC_REEL_READY',r['duration_seconds'],flush=True)


def write_brief(m,r):
    paragraphs=['Carmilla — Avaliação sistemática de tradução e dublagem pt-BR / 巴葡系统评审基线',
      'BASELINE: existing delivered audio, not a newly repaired pronunciation version. Zero new TTS/clones.',
      'Esta seleção não comprova qualidade de toda a série. Avaliar o diálogo inteiro, inclusive palavras sem comentários anteriores.',
      'Não é necessário enviar gravações pessoais. Comentários escritos com capítulo, tempo e frase são suficientes.',
      'Avaliar separadamente: Aceitável / Ajustar / Não avaliado. Não presumir aprovação quando não houver comentário.',
      'Critério de retorno: capítulo + tempo no compilado + episódio/tempo original + frase + dimensão + problema + sugestão.',
      'Amostra direcionada de seis episódios completos; não é aleatória, cega ou independente de observações anteriores.',
      'EP17/21 ampliam o contexto; ausência de comentários anteriores não implica aprovação. Nenhum experimento IPA foi aplicado aqui.',
      'O estado emocional listado é direção de produção, não confirmação auditiva da interpretação. Voz de produção não confirma identidade no áudio original.',
      'Text matches in inventory are orthographic inspection candidates, NOT proven pronunciation errors.',
      'EN below is the source text recorded in the reviewed production plan; current PT is exact reviewed unit text. Editorial annotations are retained, not silently resolved.',
      'Existing complete subtitle comparison: Review document 2714; current episode SRT files remain authoritative.',
      f'Corpus: {m["whole_season_stats"]["episode_count"]} episódios, '
      f'{m["whole_season_stats"]["subtitle_cue_count"]} legendas, '
      f'{m["whole_season_stats"]["unit_count"]} grupos de fala. '
      f'{m["whole_season_stats"]["feedback_comment_count"]} comentários arquivados; comentários não equivalem a erros confirmados.',
      'Limits: '+str(m['coverage_limits']), 'Checklist / 检查规则']
    paragraphs += [f'{key} | {name}: {text}' for key,name,text in RULES]
    paragraphs += ['Existing feedback register: reviewer statements, not confirmed causes. No comment is treated as acceptance.']
    paragraphs += [f'comment {c["comment_id"]} | EP {c["episode"]} | asset {c["asset_id"]} | {c["checklist_categories"]} | {c["content"]} | {c["location"]}' for c in m['feedback']]
    paragraphs += ['Supplemental original episode links, including known mix cases outside this reel:']
    paragraphs += [f'EP {e["episode"]:02} | Review {e["video_asset_id"]} v{e["version"]} | {e["url"]}' for e in m['episodes'] if e['episode'] not in SELECTED]
    for c in r['chapters']:
        e=next(e for e in m['episodes'] if e['episode']==c['episode'])
        paragraphs += [f'{c["id"]} | EP{e["episode"]:02} | reel {c["reel_start_seconds"]:.3f}–{c["reel_end_seconds"]:.3f}s | original 0–{e["duration_seconds"]:.3f}s',
          f'Current Review asset {e["video_asset_id"]}, version {e["version"]}; video SHA256 {e["video_sha256"]}',
          'Production roles: '+', '.join(c['production_roles'])+'; direction emotions: '+', '.join(c['direction_emotions']),
          'Unknown source identities retained: '+', '.join(c['source_unknown_unit_ids'])]
        for u in e['units']:
            paragraphs += [f'{u["id"]} | original {u["start"]:.3f}–{u["end"]:.3f}s | reel {c["reel_start_seconds"]+u["start"]:.3f}–{c["reel_start_seconds"]+u["end"]:.3f}s',
              f'Production: {u["production_voice"]} | source identity: {u.get("source_speaker","unknown")} | direction: {u["emotion"]}',
              'EN (reviewed plan): '+u['source_text'],'PT (current reviewed wording): '+u['translation']]
            notes={k:v for k,v in u.items() if k in ('issues','source_audio_readings','editorial_source_reconstructions') and v}
            if notes:
                paragraphs.append('Ressalva de origem/editorial: esta unidade possui anotações de fonte. '
                  'Conferir legendas originais e documento 2714; o EN acima não é uma confirmação acústica. '
                  'Identidade desconhecida permanece desconhecida. Evidência técnica detalhada fica no inventário privado.')
            paragraphs.append('Return: dimension / Aceitável-Ajustar-Não avaliado / description / suggested correction')
    paragraphs += ['Next step: validate changes in these complete contexts and transfer to other episodes only after explicit native acceptance.',
      'ASR checks words, not native accent quality. API success and Portuguese locale are not Brazilian pronunciation approval.',
      'No new training, no model switch and no claim of complete Brazilian-Portuguese mastery.',f'Reel SHA256: {r["output_sha256"]}']
    path=ROOT/'Carmilla_ptBR_systematic_review_brief_v1.docx';document(path,paragraphs)
    save_json(ROOT/'brief-report.private.json',{'path':str(path),'sha256':digest(path),
      'manifest_sha256':digest(ROOT/'manifest.private.json'),'render_report_sha256':digest(ROOT/'render-report.private.json')})


def publish(m,config):
    validate(m);r=read_json(ROOT/'render-report.private.json');b=read_json(ROOT/'brief-report.private.json')
    if (r['manifest_sha256']!=digest(ROOT/'manifest.private.json') or r['new_tts_count']!=0 or r['new_clone_count']!=0
      or r['kind']!='existing_delivery_baseline' or len(r['chapters'])!=6 or b['manifest_sha256']!=r['manifest_sha256']
      or b['render_report_sha256']!=digest(ROOT/'render-report.private.json')):raise ValueError('Unverified baseline artifacts')
    for c,e in zip(r['chapters'],m['chapters']):
        if c['id']!=e['id'] or c['episode']!=e['episode'] or digest(c['path'])!=c['sha256']:raise ValueError('Baseline chapter differs')
    for path,sha in [(r['output'],r['output_sha256']),(b['path'],b['sha256'])]:
        if digest(path)!=sha:raise ValueError('Artifact bytes changed')
    client=Mflix(config);before=materials(client,148);base=read_json('output/subtitle-review-update-20261020/live-before.private.json')
    verify_delivery({'all_32_published':True,'published':base['published']},before)
    auditions={x['assetId']:x for x in before if x['assetId'] in (2728,2731,2803)}
    if len(auditions)!=3:raise ValueError('Retain all prior auditions')
    ledgerpath=ROOT/'publication-ledger.private.json';ledger=read_json(ledgerpath) if ledgerpath.exists() else {'items':{}}
    specs=[('reel',r['output'],r['output_sha256'],'FINAL_CUT','Carmilla | pt-BR systematic CURRENT BASELINE v1',round(r['duration_seconds'])),
      ('brief',b['path'],b['sha256'],'DOCUMENT','Carmilla | pt-BR systematic review checklist v1.docx',0)]
    published=[]
    for key,path,sha,gate,name,duration in specs:
        state=ROOT/f'{key}-upload.private.json'
        if state.exists():
            upload=read_json(state)
            if upload['sha256']!=sha:raise ValueError('Upload differs')
        else:
            signed=client.call('createFilePresignedUrl',{'originalFileName':Path(path).name})
            if not isinstance(signed,str) or not signed.startswith('https://'):raise ValueError('Expected HTTPS upload')
            upload={'sha256':sha,'signed_url':signed,'url':signed.split('?')[0],'status':'uploading'};save_json(state,upload)
        if upload['status']!='uploaded':
            body=Path(path).read_bytes()
            if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('Upload bytes changed')
            try:response=client.http.put(upload['signed_url'],data=body,timeout=180);response.raise_for_status()
            except Exception:raise RuntimeError('Baseline upload failed; checkpoint retained') from None
            upload['status']='uploaded';save_json(state,upload)
        note=('系统评审基线：复用当前已交付01/05/17/21/26/32六个完整集，增加章节编号与当前正式PT字幕。'
          '不是新优化音轨，不是IPA返修已成功；0新TTS/0新克隆。建立译文/发音/表演/音色/对时/混音分项听审基线。'
          '全32集文本检索只是候选排查，不是已检出的语音错误；六集不是随机或盲测。原声unknown保持，制作情绪不是声学验收。'
          '请按S01-S06+合集时间/原集时间+具体句子报告，不限已知两个词。无需提供私人录音。未评不算通过。'
          '原32视频/SRT和2728/2731/2803保留。配套brief含双时间轴与EN/PT reviewed-plan对照、来源/编辑限制。'
          f' SHA256: {sha}')
        spec={'projectId':148,'gateType':gate,'name':name+' | '+sha[:12],'url':upload['url'],
          'tags':['Carmilla','pt-BR','systematic-baseline'],'durationSeconds':duration,'note':note}
        if gate=='DOCUMENT':spec['documentKind']='DOCUMENT'
        asset=register(client,spec,ledger,ledgerpath);row=check_matches(materials(client,148),spec)
        if row['assetId']!=asset or row['note']!=note:raise ValueError('Registered baseline differs')
        try:response=client.http.get(upload['url'],timeout=120);response.raise_for_status()
        except Exception:raise RuntimeError('Public verification failed; registration retained') from None
        if hashlib.sha256(response.content).hexdigest()!=sha:raise ValueError('Public artifact differs')
        published.append({'kind':key,'asset_id':asset,'name':spec['name'],'url':upload['url'],'sha256':sha})
        save_json(ROOT/'publication-progress.private.json',published)
    after=materials(client,148);verify_delivery({'all_32_published':True,'published':base['published']},after)
    if {x['assetId']:x for x in after if x['assetId'] in auditions}!=auditions:raise ValueError('Prior auditions changed')
    save_json(ROOT/'publication-result.private.json',{'published':published,'original_32_verified':True,
      'prior_auditions_retained':True,'new_tts_count':0,'new_clone_count':0,'verified_at':time.time()})
    print('SYSTEMATIC_REVIEW_VERIFIED',[(x['kind'],x['asset_id']) for x in published],flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',choices=['prepare','render','publish'],required=True)
    p.add_argument('--ffmpeg',type=Path);p.add_argument('--mcp-config',type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Business processing runs on Windows')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'pipeline.lock',timeout=0):
        if a.stage=='prepare':prepare(a.ffmpeg);return
        m=read_json(ROOT/'manifest.private.json');validate(m)
        if a.stage=='render':render(m,a.ffmpeg)
        else:publish(m,a.mcp_config)


if __name__=='__main__':main()
