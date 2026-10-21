"""Prepare a bounded, source-bound Gemini audition from actual new Review comments."""
import sys
from pathlib import Path
from translate import read_json,save_json,fingerprint
from dub_episode import digest
from publish_season_candidates import candidates,PUBLICATION
from rerun_carmilla_season import validate_reviewed_plan
from resume_season_publication import retained_delivery

ROOT=Path('output/gemini-feedback-pilot-20261021')
VOICES={'Laura':'Leda','Carmilla':'Kore','Father':'Charon','Mother':'Gacrux','Irina':'Zephyr','Narrator_EP01':'Fenrir'}
# IDs with repeated words remain explicit location candidates, not confirmed alignment.
SELECTION=[
 (5,'e05-11',[7700]),
 (1,'e01-7',[7693]),(1,'e01-17',[7694]),(1,'e01-20',[7695]),
 (2,'e02-16',[7696]),(2,'e02-18',[7696]),
 (4,'e04-1',[7698]),(4,'e04-9',[7699]),
 (9,'e09-12',[7702]),(9,'e09-17',[7704]),(10,'e10-18',[7706]),
 (11,'e11-3',[7708]),(11,'e11-10',[7709]),(12,'e12-9',[7803]),
 (13,'e13-14',[7806]),(13,'e13-15',[7806]),(14,'e14-5',[7807]),
 (24,'e24-2',[7808]),(24,'e24-3',[7809]),(24,'e24-12',[7810]),
 (26,'e26-4',[7811]),(26,'e26-18',[7812,7813]),
 (27,'e27-7',[7814]),(27,'e27-3',[7816]),(28,'e28-14',[7817]),
 (29,'e29-9',[7818]),(30,'e30-11',[7819]),(30,'e30-13',[7819]),(30,'e30-10',[7820]),
 (32,'e32-7',[7823]),(32,'e32-8',[7823]),(32,'e32-9',[7823]),(32,'e32-11',[7823])]


def main():
 if sys.platform!='win32':raise ValueError('Prepare business material on Windows')
 feedback_path=Path('output/review-feedback/2026-10-21/comments-all.private.json')
 feedback=read_json(feedback_path)
 if feedback['errors'] or len(feedback['results'])!=65:raise ValueError('Incomplete new feedback')
 comments={c['commentId']:(r,c) for r in feedback['results'] for c in r['comments']}
 available=candidates();items=[]
 for n,cue,ids in SELECTION:
  folder=available[n];plan=read_json(folder/'plan.json');validate_reviewed_plan(folder,plan)
  report=read_json(folder/'render-report.json');receipt_path=PUBLICATION/f'episode-{n:02}'/report['output_sha256']/'publication-result.json'
  receipt=read_json(receipt_path)
  retained_delivery(n,folder,receipt,receipt,receipt_path.parent/'candidate.json')
  for cid in ids:
   target,_=comments[cid]
   if target['kind']!='video' or target['episode']!=n or target['material']['assetId']!=receipt['asset_id']:raise ValueError('Comment belongs to a different version')
  unit=next(u for u in plan['units'] if cue in u['cue_ids'])
  voice=VOICES[unit['production_voice']]
  emotion=unit['emotion']
  direction={'calm':'Fala natural e contida, sem soar como locução publicitária.',
   'fearful':'Medo real e urgência na cena; voz tensa, sem virar um suspiro.',
   'surprised':'Surpresa genuína na cena, com entonação interrogativa quando houver pergunta.',
   'sad':'Tristeza contida e humana, sem exagerar pausas.',
   'angry':'Raiva intensa e ameaça na cena, mantendo clareza e identidade vocal.'}.get(emotion,'Interpretação dramática natural, conforme o texto.')
  if ids[0] in (7698,7808,7809,7811,7819,7820) or cue=='e02-18':
   direction+=' Um grito curto e intenso coerente com a fala, não um suspiro; sem prolongar desnecessariamente.'
  direction+=' Não acrescente risadas, palavras ou sons não solicitados. Diga a fala inteira de modo conectado.'
  paths=[folder/'plan.json',folder/'reviewed.json',folder/'screenplay-context.json',receipt_path,feedback_path]
  items.append({'id':f'ep{n:02}-{cue}','episode':n,'comment_ids':ids,'cue_ids':unit['cue_ids'],
   'text':unit['translation'],'voice':voice,'production_character':unit['production_voice'],
   'source_speaker':unit.get('source_speaker','unknown'),'emotion_evidence':emotion,
   'direction':direction,'start':unit['start'],'end':unit['end'],
   'video_asset_id':receipt['asset_id'],'video_version':receipt['version'],
   'original_video_path':str(folder/f'Carmilla_EP{n:02}_pt-BR_season-revision.mp4'),
   'original_video_sha256':receipt['video_sha256'],'location_status':'comment_phrase_candidate_not_human_confirmed',
   'input_sha256':{str(p):digest(p) for p in paths}})
 manifest={'project_id':148,'model':'gemini-2.5-pro-preview-tts','items':items,'preset_voices':True,
   'cloning_performed':False,'native_listening_passed':False,
   'not_addressed_by_tts_comment_ids':[7802,7804,7805,7821,7822],
   'scope':'Audition problem phrases only; not replacement episodes or final mixing.'}
 ROOT.mkdir(parents=True,exist_ok=True);path=ROOT/'manifest.private.json'
 if path.exists():
  if fingerprint(read_json(path))!=fingerprint(manifest):raise ValueError('Existing audition manifest changed')
 else:save_json(path,manifest)
 print('GEMINI_MANIFEST_READY',len(items),'NO_NEW_CLONE',flush=True)


if __name__=='__main__':main()
