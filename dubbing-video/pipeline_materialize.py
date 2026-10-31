"""Materialize frozen production candidates and role reference plans as source media arrives."""
import argparse
import copy
from pathlib import Path
import sys
import time
from dub_episode import digest
from translate import read_json,save_json
import prepare_review_editorial_queue as editorial
from pipeline_speech import checked_units


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True);parser.add_argument('--hours',type=int,default=1)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if sys.platform!='win32' or not 1<=args.hours<=168:raise ValueError('Bounded Windows input preparation only')
    bundle=read_json(args.bundle);bundle_sha=digest(args.bundle);deadline=time.time()+args.hours*3600
    registry={'schema_version':1,'voices':[],'episodes':[]}
    def media_path(project,episode):
        suffix='pipeline-media-20261031' if project==100 else 'pipeline-media-20261031-v2'
        return Path(f'output/review-project-{project}/episode-{episode:02d}/{suffix}/media.private.json')
    for proposal in bundle['episodes']:
        project,episode=proposal['project_id'],proposal['episode'];folder=editorial.folder_for(project,episode)
        result_path=folder/'editorial-result.private.json';source_path=folder/'source-input.private.json'
        if digest(result_path)!=proposal['baseline_result_sha256']:raise ValueError('Bundle baseline changed')
        context=read_json(source_path);candidate=copy.deepcopy(read_json(result_path)['candidate'])
        decision={k:v for k,v in proposal.items() if k!='uses_reviewed_production_edits'}
        decision.update(source_input_sha256=digest(source_path),audit_report_path=str(args.audit),audit_report_sha256=digest(args.audit),
                        media_receipt_path=str(media_path(project,episode)),input_bundle_sha256=bundle_sha)
        if proposal.get('uses_reviewed_production_edits'):
            production=folder.parent/'editorial-production-candidate-20261031-v2/editorial-production.private.json'
            edit_plan=Path('output/four-dramas-20261030/reviewed-text-edits-20261031')/f'project-{project}-episode-{episode:02d}.private.json'
            candidate=read_json(production)['candidate']
            decision.update(production_candidate_path=str(production),production_edit_plan_path=str(edit_plan))
        if decision['units']:checked_units(context['timed_source'],candidate,decision)
        elif set(h['cue_id'] for h in decision['holds'])!={r['id'] for r in context['timed_source']}:
            raise ValueError('All-held episode must retain every source cue')
        path=folder.parent/'pipeline-decision-20261031.private.json'
        if path.exists() and read_json(path)!=decision:raise ValueError('Existing production decision changed')
        if not path.exists():save_json(path,decision)
        entry={'project_id':project,'episode':episode,'decision_path':str(path),'decision_sha256':digest(path)}
        if project==100 and episode==1:entry['legacy_audio_root']='output/review-project-100/episode-01/audio-production-20261031-v2'
        registry['episodes'].append(entry)
    while True:
        voice_entries=[]
        for proposal in bundle['reference_proposals']:
            project,role=proposal['project_id'],proposal['role'];plans=Path(f'output/review-project-{project}/pipeline-voice-plans-20261031');plans.mkdir(exist_ok=True)
            path=plans/(role+'.private.json')
            if not path.exists():
                inputs={};segments=[];ready=True
                for item in proposal['source_candidates']:
                    episode=item['episode'];mp=media_path(project,episode)
                    if not mp.exists():ready=False;break
                    media=read_json(mp)
                    if media['source']['project_id']!=project or media['source']['episode']!=episode:raise ValueError('Reference media scope differs')
                    folder=editorial.folder_for(project,episode);source=read_json(folder/'source-input.private.json')
                    rows=source['timed_source'];row=next(r for r in rows if r['id']==item['cue_id'])
                    result=read_json(folder/'editorial-result.private.json');cue=next(c for c in result['candidate']['cues'] if c['id']==row['id'])
                    if cue['script_role']!=role or cue['issues'] or row['text']!=item['source_text']:raise ValueError('Reference role candidate changed')
                    index=rows.index(row);words=row.get('words',[])
                    start=min([row['start']]+[w['start'] for w in words]);end=max([row['end']]+[w['end'] for w in words])
                    before=rows[index-1]['end'] if index else 0;after=rows[index+1]['start'] if index+1<len(rows) else media['dialogue']['seconds']
                    start=max(0,start-.1,before+.02 if index else 0);end=min(end+.1,after-.02)
                    if end<=start:raise ValueError('Reference window collapses')
                    audio=media['dialogue']
                    inputs.update({str(mp):digest(mp),audio['path']:audio['sha256'],str(folder/'source-input.private.json'):digest(folder/'source-input.private.json'),str(folder/'editorial-result.private.json'):digest(folder/'editorial-result.private.json')})
                    segments.append({'path':audio['path'],'sha256':audio['sha256'],'start':start,'end':end,'cue_ids':[row['id']],
                                     'source_text':row['text'],'script_quote':cue['script_quote'],'source_role_candidate':role})
                if not ready:continue
                seconds=sum(r['end']-r['start'] for r in segments)
                if seconds<3:continue
                plan={'project_id':project,'role':role,'platform':'minimax' if seconds>=10 else 'cartesia',
                      'source_attribution':'known screenplay role candidate, original actor identity not verified',
                      'inputs_sha256':inputs,'segments':segments,'no_artificial_padding_or_repetition':True,
                      'native_listening_passed':False}
                save_json(path,plan)
            voice_entries.append({'project_id':project,'role':role,'plan_path':str(path),'plan_sha256':digest(path),
                                  'approval_path':str(Path(f'output/review-project-{project}/pipeline-voices-20261031')/role/'clone-approval.private.json')})
        # Include explicitly prepared/approved special roles without replacing their frozen plans.
        for project in editorial.COUNTS:
            plans=Path(f'output/review-project-{project}/pipeline-voice-plans-20261031')
            for path in plans.glob('*.private.json'):
                plan=read_json(path);role=plan['role']
                if any(j['project_id']==project and j['role']==role for j in voice_entries):continue
                voice_entries.append({'project_id':project,'role':role,'plan_path':str(path),'plan_sha256':digest(path),
                                      'approval_path':str(Path(f'output/review-project-{project}/pipeline-voices-20261031')/role/'clone-approval.private.json')})
        registry['voices']=voice_entries;save_json(args.registry,registry)
        print('PIPELINE_INPUTS_READY',len(registry['episodes']),len(voice_entries),flush=True)
        if args.once or time.time()>=deadline:return
        time.sleep(30)


if __name__=='__main__':main()
