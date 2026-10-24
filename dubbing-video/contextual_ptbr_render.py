"""Render and add a genuinely changed contextual candidate, preserving old deliveries."""
import hashlib
import math
from pathlib import Path
import re
import subprocess
import time
import unicodedata

from translate import read_json,save_json,load_segments,write_srt,fingerprint
from dub_episode import digest,read_audio,write_audio,RATE,probe
from publish_review import document,materials,register,check_matches
from notify_season_complete import verify_delivery
from mflix_client import Mflix
from contextual_ptbr_candidate import ROOT,validate,generated,known_groups


def subtitle_rows(s):
    rows=load_segments(s['base']['subtitle']);windows={}
    for u in s['source_report']['utterances']:
        for w in u['source_windows']:
            key=(round(w['start']*1000),round(w['end']*1000))
            if key in windows:raise ValueError('Ambiguous subtitle time binding')
            windows[key]=w['id']
    out=[];used=set();by_id={}
    for row in rows:
        key=(round(row['start']*1000),round(row['end']*1000))
        if key not in windows:raise ValueError('Current subtitle time differs from reviewed source window')
        cid=windows[key];used.add(cid)
        pt=s['cue_changes'].get(cid,row['text']);by_id[cid]=pt
        out.append({**row,'cue_id':cid,'episode':str(s['episode']),'translation':pt})
    if not set(s['cue_changes']).issubset(used):raise ValueError('Subtitle change did not map to existing cue')
    words=lambda x:re.findall(r'\w+',x.casefold())
    for g in s['groups']:
        captions=' '.join(by_id[cid] for u in g['source_units'] for cid in u['cue_ids'])
        if words(captions)!=words(g['caption']):raise ValueError('Candidate speech and subtitle words differ')
    return out


def run(args,**kwargs):
    try:return subprocess.run([str(x) for x in args],check=True,capture_output=True,**kwargs)
    except subprocess.CalledProcessError:raise RuntimeError('Contextual media operation failed; inspect saved stage, no paid retry') from None


def payload(path,ffmpeg,stream):
    return run([ffmpeg,'-v','error','-i',Path(path).resolve(),'-map',stream,'-c','copy','-f','hash','-hash','sha256','-'],text=True).stdout.strip()


def verify_ready(m):
    audio=generated(m);f=read_json(ROOT/'fit-report.private.json')
    if (not f['ready'] or f['blocked'] or f['manifest_sha256']!=digest(ROOT/'manifest.private.json')
      or f['generation_sha256']!=digest(ROOT/'generation-result.private.json') or not f['no_speech_truncated']):
        raise ValueError('All contextual groups must fit without truncation or excess speed')
    expected=[u for s in m['scenes'] for u in s['groups']]
    if [r['unit_id'] for r in f['units']]!=[u['id'] for u in expected]:raise ValueError('Fit coverage differs')
    fitted={r['unit_id']:r for r in f['units']}
    for u in expected:
        r=fitted[u['id']]
        if r['unknown_retained']!=u['unknown_retained']:raise ValueError('Unknown identity policy changed')
        if not u['unknown_retained']:
            a=audio[fingerprint(u['request'])]
            if (r['raw_sha256']!=a['sha256'] or digest(r['path'])!=r['sha256'] or not 1<=r['atempo_factor']<=1.2
              or r['start']!=u['start'] or r['start']+r['duration_seconds']>u['audio_end_limit']+.000001):
                raise ValueError('Fitted candidate differs from approved policy')
    screening=read_json(ROOT/'content-screening.private.json')['results']
    if [r['unit_id'] for r in screening]!=[u['id'] for u in known_groups(m)]:raise ValueError('Content screening incomplete')
    for u,r in zip(known_groups(m),screening):
        a=audio[fingerprint(u['request'])]
        if r['audio_sha256']!=a['sha256'] or r['expected_text']!=u['caption']:raise ValueError('Screening input differs')
    return audio,fitted,screening


def render(m,ffmpeg):
    import numpy as np
    validate(m);audio,fitted,screening=verify_ready(m)
    report_path=ROOT/'render-report.private.json';output=ROOT/'Carmilla_ptBR_contextual_candidate_AB_v1.mp4'
    if report_path.exists():
        report=read_json(report_path)
        for path,sha in report['artifact_sha256'].items():
            if digest(path)!=sha:raise ValueError('Previously rendered artifact changed')
        if (report['manifest_sha256']!=digest(ROOT/'manifest.private.json')
          or report['generation_sha256']!=digest(ROOT/'generation-result.private.json')
          or report['fit_report_sha256']!=digest(ROOT/'fit-report.private.json')
          or report['screening_sha256']!=digest(ROOT/'content-screening.private.json')):raise ValueError('Rendered basis differs')
        for c in report['chapters']:
            if digest(c['path'])!=c['sha256']:raise ValueError('Previously rendered chapter changed')
        print('CONTEXT_REEL_REUSED',flush=True);return
    chapters=[];combined=[];cursor=0.
    for s in m['scenes']:
        folder=ROOT/f'episode-{s["episode"]:02}';folder.mkdir(exist_ok=True)
        candidate_rows=subtitle_rows(s);candidate_srt=folder/'candidate.srt';write_srt(candidate_srt,candidate_rows)
        original_rows=[{**r,'episode':str(s['episode']),'translation':r['text']} for r in load_segments(s['base']['subtitle'])]
        duration=s['base']['duration_seconds'];dialogue=np.zeros(math.ceil(duration*RATE),dtype='float32')
        replaced={uid for u in s['groups'] if not u['unknown_retained'] for uid in u['source_unit_ids']}
        placements=[]
        for u in s['source_report']['utterances']:
            if u['id'] in replaced:continue
            placements.append((u.get('audio_start',u['start']),u['fitted_path'],u['id'],'original-retained'))
        for u in s['groups']:
            if u['unknown_retained']:continue
            f=fitted[u['id']];placements.append((f['start'],f['path'],u['id'],'candidate'))
        intervals=[]
        for start,path,uid,kind in placements:
            samples=read_audio(path,ffmpeg);pos=round(start*RATE)
            if pos+len(samples)>len(dialogue):raise ValueError('Speech outside original episode')
            intervals.append((pos,pos+len(samples),uid));dialogue[pos:pos+len(samples)]+=samples
        intervals.sort()
        if any(a[1]>b[0]+48 for a,b in zip(intervals,intervals[1:])):raise ValueError('Candidate speech overlaps another unit')
        dialogue_path=folder/'dialogue.wav';mixed=folder/'mix.wav';write_audio(dialogue_path,dialogue)
        run([ffmpeg,'-v','error','-y','-i',dialogue_path,'-i',s['assets']['bgm'],'-i',s['assets']['sfx'],
          '-filter_complex',f'[0:a]apad,atrim=duration={duration}[d];[1:a]apad,atrim=duration={duration}[b];[2:a]apad,atrim=duration={duration}[s];[d][b][s]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=true[out]',
          '-map','[out]','-ar','48000','-ac','2','-c:a','pcm_s16le',mixed])
        master=folder/'candidate-picture-copy.mp4'
        run([ffmpeg,'-v','error','-y','-i',s['assets']['video'],'-i',mixed,'-map','0:v:0','-map','1:a:0',
          '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',master])
        original_picture=payload(s['assets']['video'],ffmpeg,'0:v:0')
        if payload(master,ffmpeg,'0:v:0')!=original_picture:raise ValueError('Original video picture changed')
        for label,video,rows in [('A',Path(s['base']['video']),original_rows),('B',master,candidate_rows)]:
            shifted=[]
            for row in rows:
                if row['end']<=s['start'] or row['start']>=s['end']:continue
                shifted.append({**row,'start':max(0,row['start']-s['start']),
                  'end':min(s['end'],row['end'])-s['start'],'episode':'reel'})
            sub=folder/f'{s["id"]}-{label}.srt';write_srt(sub,shifted)
            caption=f'{s["id"]} {label} | '+('CURRENT DELIVERY' if label=='A' else 'NEW CANDIDATE - NATIVE REVIEW PENDING')
            vf=(f'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,'
              f'subtitles={sub.name}:force_style=\'Fontsize=18,MarginV=35\','
              f'drawbox=x=0:y=0:w=iw:h=55:color=black@0.8:t=fill,drawtext=text=\'{caption}\':fontcolor=white:fontsize=19:x=(w-tw)/2:y=18')
            clip=folder/f'{s["id"]}-{label}.mp4'
            run([ffmpeg,'-v','error','-y','-ss',s['start'],'-i',video.resolve(),'-t',s['end']-s['start'],
              '-map','0:v:0','-map','0:a:0','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',
              '-c:a','aac','-b:a','160k','-ar','48000','-ac','2','-movflags','+faststart',clip.name],cwd=folder)
            seconds=float(probe(clip,ffmpeg)['format']['duration'])
            chapters.append({'scene_id':s['id'],'episode':s['episode'],'label':label,'path':str(clip),'sha256':digest(clip),
              'reel_start':cursor,'reel_end':cursor+seconds,'source_start':s['start'],'source_end':s['end'],
              'duration_seconds':seconds,'subtitle_sha256':digest(sub),'original_picture_payload':original_picture,
              'baseline_video_sha256':s['base']['video_sha256']})
            combined += [{**r,'start':r['start']+cursor,'end':r['end']+cursor} for r in shifted]
            cursor+=seconds;print('CONTEXT_CHAPTER_READY',s['id'],label,round(seconds,3),flush=True)
    listing=ROOT/'concat.txt';listing.write_text(''.join(f"file '{Path(c['path']).resolve().as_posix()}'\n" for c in chapters),encoding='utf-8')
    run([ffmpeg,'-v','error','-y','-f','concat','-safe','0','-i',listing.resolve(),'-c','copy','-movflags','+faststart',output.resolve()])
    subtitle=ROOT/'Carmilla_ptBR_contextual_candidate_AB_v1.srt';write_srt(subtitle,combined)
    brief=ROOT/'Carmilla_ptBR_contextual_candidate_changes_v1.docx'
    norm=lambda t:re.findall(r'\w+',unicodedata.normalize('NFC',t).casefold())
    differences=[r for r in screening if norm(r['expected_text'])!=norm(r['asr_transcript'])]
    paragraphs=['Carmilla — nova candidata contextual A/B / 实际改动的完整语境候选',
      'A = áudio atualmente entregue; B = nova candidata. Não é o baseline 2808 republicado.',
      'B usa clones MiniMax já existentes, um por personagem. Laura/Carmilla mudam de configuração Cartesia em algumas falas para clone MiniMax existente; timbre/semelhança ainda precisam de avaliação.',
      'Sem clonagem nova, IPA ou grafia inventada. Três ligações de pensamentos completos; quatro ajustes de texto. Pausas hesitantes apoiadas pela fonte foram preservadas.',
      'Amostra direcionada de três contextos, não aprovação da série inteira. Direção emocional e maiúsculas não comprovam interpretação executada.',
      'EP24 corresponde ao storyboard EP25 WOUNDED. Usado o trecho atualizado e a associação revisada; não importar falas do antigo roteiro EP24.',
      'A identidade original de e17-16 continua desconhecida. A gravação de produção anterior é mantida sem nova síntese.',
      'As legendas B preservam os tempos originais, com ajustes de texto identificados abaixo; os arquivos atuais na Review não são sobrescritos.',
      'Avaliar: naturalidade brasileira de toda a conversa, palavras não apontadas antes, sentido/negação/prazos, identidade vocal, interpretação, ritmo e mixagem.',
      'Comentar com D1/D2/D3 + A/B + tempo + frase. Escolher melhor/pior/sem diferença e explicar. Não é necessário enviar gravações pessoais.',
      'O rastreio textual da série inteira identifica candidatos para análise, não erros acústicos confirmados. Não transformar ausência de comentário em aprovação.']
    for c in chapters:paragraphs.append(f'{c["scene_id"]}{c["label"]}: reel {c["reel_start"]:.3f}–{c["reel_end"]:.3f}s; EP{c["episode"]:02} original {c["source_start"]:.3f}–{c["source_end"]:.3f}s')
    for s in m['scenes']:
        for g in s['groups']:
            old=' '.join(u['translation'] for u in g['source_units']);src=' '.join(u['source_text'] for u in g['source_units'])
            paragraphs += [f'{s["id"]} | {g["id"]} | EP{g["episode"]:02} {g["start"]:.3f}–{g["end"]:.3f}s',
              f'EN (reviewed source plan): {src}',f'A: {old}',f'B: {g["caption"]}',
              f'Production role: {g["production_voice"]}; source identity: {g["source_speaker"]}; emotional direction: {g["emotion_direction"]}.']
            if not g['unknown_retained']:
                f=fitted[g['id']];paragraphs.append(f'Natural audio: {audio[fingerprint(g["request"])]["duration_seconds"]:.3f}s; fitted {f["duration_seconds"]:.3f}s; factor {f["atempo_factor"]:.4f}; no speech cut.')
    paragraphs+=['Machine transcript differences — review leads only, not proven mispronunciation:']
    paragraphs += [f'{r["unit_id"]}: intended {r["expected_text"]} / ASR {r["asr_transcript"]}' for r in differences]
    paragraphs += ['If whole-context native review still shows broad accent defects, evaluate a different voice-preserving route instead of extending unproven per-word controls.']
    document(brief,paragraphs)
    artifacts={str(p):digest(p) for p in [output,subtitle,brief]}
    report={'manifest_sha256':digest(ROOT/'manifest.private.json'),'generation_sha256':digest(ROOT/'generation-result.private.json'),
      'fit_report_sha256':digest(ROOT/'fit-report.private.json'),'screening_sha256':digest(ROOT/'content-screening.private.json'),
      'artifact_sha256':artifacts,'output':str(output),'output_sha256':digest(output),'subtitle':str(subtitle),'brief':str(brief),
      'chapters':chapters,'duration_seconds':float(probe(output,ffmpeg)['format']['duration']),
      'source_audio_in_output':False,'unknown_source_group_retained':True,'new_clone_count':0,
      'native_listening_passed':False,'asr_difference_count':len(differences),'asr_differences':differences}
    save_json(report_path,report);print('CONTEXT_REEL_READY',report['duration_seconds'],flush=True)


def publish(m,config):
    validate(m);verify_ready(m);r=read_json(ROOT/'render-report.private.json')
    if (r['manifest_sha256']!=digest(ROOT/'manifest.private.json') or r['generation_sha256']!=digest(ROOT/'generation-result.private.json')
      or r['fit_report_sha256']!=digest(ROOT/'fit-report.private.json') or r['screening_sha256']!=digest(ROOT/'content-screening.private.json')
      or r['new_clone_count']!=0 or r['source_audio_in_output'] or len(r['chapters'])!=6):raise ValueError('Unverified contextual render')
    if [(c['scene_id'],c['label']) for c in r['chapters']]!=[(s['id'],label) for s in m['scenes'] for label in ('A','B')]:raise ValueError('Comparison coverage changed')
    for path,sha in r['artifact_sha256'].items():
        if digest(path)!=sha:raise ValueError('Candidate output changed')
    for c in r['chapters']:
        if digest(c['path'])!=c['sha256']:raise ValueError('Candidate chapter changed')
    client=Mflix(config);before=materials(client,148);old=read_json('output/subtitle-review-update-20261020/live-before.private.json')
    verify_delivery({'all_32_published':True,'published':old['published']},before)
    retain={2728,2731,2803,2808,2809}
    projection=lambda rows:{x['assetId']:{k:x.get(k) for k in ('projectId','gateType','name','url','version','documentKind')} for x in rows if x['assetId'] in retain}
    previous=projection(before)
    if set(previous)!=retain:raise ValueError('Prior audition/reference assets missing')
    ledgerpath=ROOT/'publication-ledger.private.json';ledger=read_json(ledgerpath) if ledgerpath.exists() else {'items':{}}
    artifacts=[('reel',r['output'],'FINAL_CUT','Carmilla | pt-BR contextual NEW candidate A-B v1',round(r['duration_seconds'])),
      ('subtitles',r['subtitle'],'DOCUMENT','Carmilla | pt-BR contextual candidate A-B subtitles v1.srt',0),
      ('brief',r['brief'],'DOCUMENT','Carmilla | pt-BR contextual candidate changes v1.docx',0)]
    results=[]
    for key,path,gate,name,duration in artifacts:
        sha=r['artifact_sha256'][path];state=ROOT/f'{key}-upload.private.json'
        if state.exists():
            upload=read_json(state)
            if upload['sha256']!=sha:raise ValueError('Existing upload differs')
        else:
            signed=client.call('createFilePresignedUrl',{'originalFileName':Path(path).name})
            if not isinstance(signed,str) or not signed.startswith('https://'):raise ValueError('HTTPS upload required')
            upload={'sha256':sha,'signed_url':signed,'url':signed.split('?')[0],'status':'uploading'};save_json(state,upload)
        if upload['status']!='uploaded':
            body=Path(path).read_bytes()
            if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('Upload bytes changed')
            try:response=client.http.put(upload['signed_url'],data=body,timeout=180);response.raise_for_status()
            except Exception:raise RuntimeError('Upload failed; checkpoint retained, URL omitted') from None
            upload['status']='uploaded';save_json(state,upload)
        note=('实际新音轨完整场景候选，非旧基线重发：D1日常对白/EP05末场，D2较长剧情说明与条件句/EP17，D3多人冲突与情绪变化/EP24。'
          '每场A当前成片/B新候选。B沿用角色已有MiniMax克隆，Laura/Carmilla部分原为Cartesia，改用其已有MiniMax克隆，不冒音色相似度已通过。'
          '0新clone；4处等义口语调整、3处同角色同情绪意群连接、仅有喊叫依据的3处大写合成控制，无IPA/错误拼写。'
          '按剧本/成片匹配来源：EP24实际对应final EP25 WOUNDED；未知原声身份e17-16保持原制作录音，不新配。'
          '原源字幕时间码保留；新候选字幕/改动说明另附。实际1.2语速上限/.8后空隙、无截词，情绪/巴葡口音/音色/混音仍待专业听审。'
          '请按D1/D2/D3+A/B+时间/具体句子评整体自然度和其他未报词。不能从API或ASR成功推母语通过；未评不算通过。'
          f'机器转写分歧{r["asr_difference_count"]}处只作听审线索，详见配套说明。原32集及此前样片/文档保留。 Reel SHA256: {r["output_sha256"]}; Artifact SHA256: {sha}')
        spec={'projectId':148,'gateType':gate,'name':name+' | '+sha[:12],'url':upload['url'],
          'tags':['Carmilla','pt-BR','contextual-candidate','MiniMax'],'durationSeconds':duration,'note':note}
        if gate=='DOCUMENT':spec['documentKind']='DOCUMENT'
        aid=register(client,spec,ledger,ledgerpath);row=check_matches(materials(client,148),spec)
        if row['assetId']!=aid or row['note']!=note:raise ValueError('Candidate readback differs')
        try:response=client.http.get(upload['url'],timeout=120);response.raise_for_status()
        except Exception:raise RuntimeError('Public readback failed; registration retained') from None
        if hashlib.sha256(response.content).hexdigest()!=sha:raise ValueError('Public artifact differs')
        results.append({'kind':key,'asset_id':aid,'name':spec['name'],'url':upload['url'],'sha256':sha})
        save_json(ROOT/'publication-progress.private.json',results)
    after=materials(client,148);verify_delivery({'all_32_published':True,'published':old['published']},after)
    if projection(after)!=previous:raise ValueError('Prior assets changed during publication')
    save_json(ROOT/'publication-result.private.json',{'published':results,'original_32_verified':True,'prior_assets_retained':True,
      'new_clone_count':0,'native_listening_passed':False,'verified_at':time.time()})
    print('CONTEXT_REVIEW_VERIFIED',[(x['kind'],x['asset_id']) for x in results],flush=True)
