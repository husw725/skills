"""Bounded cross-drama episode pipeline: independent preparation, voices, speech, fit and Review."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import json
from datetime import datetime

from dub_episode import digest
from pipeline_speech import audio_root
from process_lock import process_lock
from translate import read_json,save_json,fingerprint

ROOT=Path('output/four-dramas-20261030/production-pipeline')


def choose_stage(files,holds=False):
    if files.get('delivered'):return 'delivered'
    if files.get('render'):return 'publish'
    if files.get('generation'):return 'source_holds' if holds else 'fit'
    if files.get('plan'):return 'generate' if files.get('approval') else 'speech_review'
    return 'prepare'


def recorded_worker_alive(record):
    if record.get('stage') not in ('reference_prepare','reference_check','reference_accept','clone','prepare','plan_check','generate','fit','media_check','publish'):
        return False
    if type(record.get('pid')) is not int or not record.get('command_line'):
        return False
    command=("$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "+str(record['pid'])+"'; "
             "if($p){[pscustomobject]@{CommandLine=$p.CommandLine;Started=$p.CreationDate.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress}")
    try:
        process=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,timeout=15,check=True)
        if not process.stdout.strip():return False
        data=json.loads(process.stdout)
        return data['CommandLine']==record['command_line'] and abs(datetime.fromisoformat(data['Started']).timestamp()-record['started_at'])<10
    except Exception:
        return True  # Inspection uncertainty never authorizes duplicate work.


def occupied_slots(active,records,orphan_alive):
    paid=any(job['paid'] for job in active.values())
    free=sum(not job['paid'] for job in active.values())
    for key,alive in orphan_alive.items():
        if not alive or key in active:continue
        if records[key].get('paid_stage'):paid=True
        else:free+=1
    return paid,free


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry',type=Path,required=True);parser.add_argument('--ffmpeg',type=Path,required=True)
    parser.add_argument('--audio-config',type=Path,required=True);parser.add_argument('--review-config',type=Path,required=True)
    parser.add_argument('--hours',type=int,default=72)
    parser.add_argument('--candidate-policy',type=Path)
    parser.add_argument('--asr-python',type=Path)
    parser.add_argument('--notify-config',type=Path)
    args=parser.parse_args()
    if sys.platform!='win32' or not 1<=args.hours<=168:raise ValueError('Bounded Windows production only')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'controller.lock',timeout=0):
        state_path=ROOT/'progress.private.json';state=read_json(state_path) if state_path.exists() else {'jobs':{}}
        state.setdefault('started_at',time.time());state.setdefault('expires_at',time.time()+args.hours*3600)
        active={}
        def notify_blockers():
            if not args.notify_config or not args.notify_config.exists():return
            path=ROOT/'notifications.private.json'
            receipts=read_json(path) if path.exists() else {}
            pending=[]
            for key,record in state['jobs'].items():
                if record.get('stage') not in ('needs_reconciliation','source_holds','timing_review','reference_review_pending'):continue
                event=fingerprint({'job':key,'stage':record['stage'],'last_stage':record.get('last_stage'),'reason':record.get('reason')})
                if event not in receipts:pending.append((event,key,record['stage']))
            if not pending:return
            for event,key,stage in pending:receipts[event]={'job':key,'stage':stage,'status':'sending','attempted_at':time.time()}
            save_json(path,receipts)
            from notification_watch import send
            cfg=read_json(args.notify_config)
            message='### 四剧流水线需核查\n\n'+'\n'.join(key+' · '+stage for _,key,stage in pending)+'\n\n其他已就绪集继续执行；已保留付费断点。'
            if cfg.get('keyword'):message=cfg['keyword']+'\n\n'+message
            try:send(cfg,message)
            except Exception as exc:
                for event,_,_ in pending:receipts[event].update(status='delivery_failed_or_unknown',error_type=type(exc).__name__)
            else:
                for event,_,_ in pending:receipts[event].update(status='sent')
            save_json(path,receipts)
        def persist():
            state.update(stage='episode_pipeline_running',updated_at=time.time(),active_jobs=list(active))
            save_json(state_path,state)
        def launch(key,stage,command,paid=False,python=None):
            previous=state['jobs'].get(key,{})
            identity=fingerprint(command)
            # Ambiguous interrupted paid stages may be resumed only through the existing safe cache engine.
            attempts=previous.get('stage_attempts',{})
            if attempts.get(stage,0)>=3:
                state['jobs'][key]={**previous,'stage':'needs_reconciliation','failed_stage':stage};return
            attempts[stage]=attempts.get(stage,0)+1
            state['jobs'][key]={**previous,'stage':stage,'command_fingerprint':identity,'stage_attempts':attempts,
                               'started_at':time.time(),'paid_stage':paid}
            persist()
            log=(ROOT/(key.replace(':','-')+'-'+stage+'.private.log')).open('a',encoding='utf-8')
            env=__import__('os').environ.copy();env['MFLIX_DIRECT_CONNECTION']='1'
            executable=str(python) if python else sys.executable
            process=subprocess.Popen([executable,'-u',*command],stdout=log,stderr=log,env=env)
            active[key]={'process':process,'log':log,'stage':stage,'paid':paid,'started':time.monotonic()}
            state['jobs'][key].update(pid=process.pid,command_line=subprocess.list2cmdline([executable,'-u',*command]));persist()
        while time.time()<state['expires_at']:
            for key,item in list(active.items()):
                code=item['process'].poll()
                if code is None:continue
                item['log'].close();del active[key]
                state['jobs'][key].update(stage='stage_finished' if code==0 else 'needs_reconciliation',
                                         last_stage=item['stage'],exit_code=code,finished_at=time.time())
                persist()
            registry=read_json(args.registry)
            if registry.get('schema_version')!=1:raise ValueError('Pipeline registry schema changed')
            orphan_alive={k:recorded_worker_alive(r) for k,r in state['jobs'].items() if k not in active}
            paid_busy,free_busy=occupied_slots(active,state['jobs'],orphan_alive)
            speech_waiting=False
            for episode_job in registry.get('episodes',[]):
                if episode_job.get('legacy_audio_root'):continue
                audio=audio_root(Path(episode_job['decision_path']))
                key=f"episode:{episode_job['project_id']}:{episode_job['episode']}"
                if (audio/'speech-approval.private.json').exists() and not (audio/'generation-result.private.json').exists() and state['jobs'].get(key,{}).get('stage')!='needs_reconciliation':
                    speech_waiting=True;break
            urgency={}
            for episode_job in registry.get('episodes',[]):
                decision_path=Path(episode_job['decision_path'])
                if not decision_path.exists():continue
                for unit in read_json(decision_path)['units']:
                    role_key=(episode_job['project_id'],unit['role'])
                    urgency[role_key]=min(urgency.get(role_key,999),episode_job['episode'])
            # Role voices are shared for the whole drama, never created per episode.
            for job in sorted(registry.get('voices',[]),key=lambda j:(urgency.get((j['project_id'],j['role']),999),j['project_id'],j['role'])):
                key=f"voice:{job['project_id']}:{job['role']}"
                if key in active:continue
                old=state['jobs'].get(key,{})
                if orphan_alive.get(key):continue
                plan_path=Path(job['plan_path'])
                if not plan_path.exists():continue
                if digest(plan_path)!=job['plan_sha256']:
                    state['jobs'][key]={**old,'stage':'needs_reconciliation','reason':'registered_reference_changed'};continue
                folder=Path(f"output/review-project-{job['project_id']}/pipeline-voices-20261031/{job['role']}")
                if (folder/'clone.private.json').exists():
                    bank=folder.parent/'voice-bank.private.json'
                    if bank.exists() and job['role'] in read_json(bank)['voices']:
                        state['jobs'][key]={**old,'stage':'voice_ready'};continue
                if old.get('stage')=='needs_reconciliation':continue
                base=['pipeline_voice.py','--plan',str(plan_path),'--ffmpeg',str(args.ffmpeg)]
                if not (folder/'reference-receipt.private.json').exists() and free_busy<2:
                    launch(key,'reference_prepare',base);free_busy+=1
                elif (folder/'reference-receipt.private.json').exists():
                    approval=Path(job['approval_path'])
                    if not approval.exists():
                        screened=folder/'reference-asr.private.json';checked=folder/'reference-candidate-check.private.json'
                        if not screened.exists() and args.asr_python and free_busy<2:
                            launch(key,'reference_check',['pipeline_reference_check.py','--ffmpeg',str(args.ffmpeg),'--role-folder',str(folder)],python=args.asr_python);free_busy+=1
                        elif screened.exists() and not checked.exists() and args.candidate_policy and free_busy<2:
                            launch(key,'reference_accept',['pipeline_reference_accept.py','--plan',str(plan_path),'--policy',str(args.candidate_policy),'--config',str(args.audio_config)]);free_busy+=1
                        else:state['jobs'][key]={**old,'stage':'reference_review_pending' if checked.exists() else 'reference_check_pending'}
                    elif not paid_busy and not speech_waiting:
                        launch(key,'clone',base+['--approval',str(approval),'--config',str(args.audio_config)],True);paid_busy=True
            for job in sorted(registry.get('episodes',[]),key=lambda j:(j['episode'],j['project_id'])):
                key=f"episode:{job['project_id']}:{job['episode']}"
                if key in active:continue
                old=state['jobs'].get(key,{})
                if orphan_alive.get(key):continue
                decision_path=Path(job['decision_path'])
                if not decision_path.exists():
                    state['jobs'][key]={**old,'stage':'production_decision_pending'};continue
                if digest(decision_path)!=job['decision_sha256']:
                    state['jobs'][key]={**old,'stage':'needs_reconciliation','reason':'registered_decision_changed'};continue
                decision=read_json(decision_path)
                if not decision['units'] and not job.get('legacy_audio_root'):
                    state['jobs'][key]={**old,'stage':'source_holds'};continue
                audio=audio_root(decision_path,decision)
                if job.get('legacy_audio_root'):audio=Path(job['legacy_audio_root'])
                delivery=decision_path.parent/'pipeline-publication-20261031/progress.private.json'
                if delivery.exists():
                    done=read_json(delivery)
                    if done['stage']=='review_candidate_delivered' and (audio/'render-report.private.json').exists() and read_json(audio/'render-report.private.json')['output_sha256']==done['video_sha256']:state['jobs'][key]={**old,'stage':'delivered',**done};continue
                if old.get('stage')=='needs_reconciliation':continue
                report=audio/'render-report.private.json';approval=audio/'speech-approval.private.json'
                phase=choose_stage({'render':report.exists(),'generation':(audio/'generation-result.private.json').exists(),
                                    'plan':(audio/'speech-plan.private.json').exists(),'approval':approval.exists()},bool(decision['holds']))
                fit_report=audio/'fit-report.private.json'
                if phase=='fit' and fit_report.exists() and read_json(fit_report).get('blocked'):phase='timing_review'
                if phase=='speech_review' and args.candidate_policy and free_busy<2:
                    launch(key,'plan_check',['pipeline_plan_check.py','--decision',str(decision_path),'--policy',str(args.candidate_policy)])
                    free_busy+=1;continue
                if phase in ('source_holds','speech_review','timing_review'):
                    state['jobs'][key]={**old,'stage':phase};continue
                base=['pipeline_speech.py','--decision',str(decision_path)]
                if phase=='prepare':
                    media=Path(decision['media_receipt_path'])
                    if not media.exists():state['jobs'][key]={**old,'stage':'media_pending'};continue
                    roles={u['role'] for u in decision['units']};available=set()
                    bank=Path(f"output/review-project-{job['project_id']}/pipeline-voices-20261031/voice-bank.private.json")
                    if bank.exists():available.update(read_json(bank)['voices'])
                    if job['project_id']==100:available.update(read_json('output/review-project-100/voice-bank-minimax-20261031/voice-bank.private.json')['voices'])
                    if roles-available:state['jobs'][key]={**old,'stage':'voices_pending','missing_roles':sorted(roles-available)};continue
                    if free_busy<2:launch(key,'prepare',base+['--stage','prepare']);free_busy+=1
                elif phase=='generate' and not paid_busy:
                    launch(key,'generate',base+['--stage','generate','--config',str(args.audio_config)],True);paid_busy=True
                elif phase=='fit' and free_busy<2:
                    launch(key,'fit',base+['--stage','fit','--ffmpeg',str(args.ffmpeg)]);free_busy+=1
                elif phase=='publish' and free_busy<2:
                    media_approval=audio/'publication-approval.private.json'
                    if not media_approval.exists():
                        launch(key,'media_check',['pipeline_delivery_check.py','--root',str(audio),'--ffmpeg',str(args.ffmpeg)])
                        free_busy+=1;continue
                    launch(key,'publish',['pipeline_publish.py','--project',str(job['project_id']),'--episode',str(job['episode']),
                        '--report',str(report),'--approval',str(media_approval),'--config',str(args.review_config),
                        '--ffmpeg',str(args.ffmpeg),'--publish']);free_busy+=1
            persist()
            notify_blockers()
            time.sleep(10)
        state.update(stage='dispatch_window_ended_waiting_children',updated_at=time.time());save_json(state_path,state)
        # Dispatch deadline is not a promise that outstanding API work is finished.
        deadline=time.monotonic()+3600
        while active and time.monotonic()<deadline:
            for key,item in list(active.items()):
                if item['process'].poll() is not None:
                    item['log'].close();del active[key]
            state.update(active_jobs=list(active),updated_at=time.time());save_json(state_path,state)
            if active:time.sleep(10)
        state.update(stage='dispatch_window_ended_children_pending' if active else 'pipeline_window_finished',
                     active_jobs=list(active),updated_at=time.time());save_json(state_path,state)
        for item in active.values():item['log'].close()  # No kill or automatic paid re-submit.


if __name__=='__main__':main()
