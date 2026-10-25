"""Screen completed WAVs while the finite generation job continues; never submit audio."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

from translate import read_json,save_json,fingerprint
from dub_episode import digest
from process_lock import process_lock
from contextual_ptbr_candidate import ROOT,validate,known_groups
from clone_feedback_v2 import completed


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ffmpeg',type=Path,required=True);a=p.parse_args()
    if sys.platform!='win32':p.error('Run local screening on Windows')
    from faster_whisper import WhisperModel
    import numpy as np
    m=read_json(ROOT/'manifest.private.json');validate(m);groups=known_groups(m)
    local=Path('output/tools/source-asr-models/large-v3');v=read_json(local/'verified.json');official=read_json(local/'official-source.json')
    expected=next(f['lfs']['sha256'] for f in official['siblings'] if f['rfilename']=='model.bin')
    if (v.get('official_hashes_verified') is not True or v['repo']!='Systran/faster-whisper-large-v3'
      or v['revision']!=official['revision'] or digest(local/'model.bin')!=expected):raise ValueError('Pinned ASR changed')
    decoding={'language':'pt','beam_size':5,'temperature':0,'condition_on_previous_text':False,'vad_filter':False}
    with process_lock(ROOT/'screening.lock',timeout=0):
        model=WhisperModel(str(local.resolve()),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1)
        records={};deadline=time.monotonic()+1800
        while len(records)<len(groups):
            if time.monotonic()>deadline:raise RuntimeError('Bounded screening wait ended; completed records retained')
            state=ROOT/'generation-progress.private.json'
            progress=read_json(state) if state.exists() else {}
            for u in groups:
                if u['id'] in records:continue
                key=fingerprint(u['request'])
                if key not in progress:continue
                r=progress[key]
                if r['request']!=u['request'] or digest(r['path'])!=r['sha256']:raise ValueError('Completed input changed')
                _,receipt=completed(Path(r['path']).parent,u['request'])
                if receipt['task_id']!=r['task_id']:raise ValueError('Completed task changed')
                target=ROOT/'content-screening'/f'{u["id"]}.private.json'
                if target.exists():
                    record=read_json(target)
                    if (record['audio_sha256']!=r['sha256'] or record['expected_text']!=u['caption']
                      or record['decoding']!=decoding or record['model_revision']!=v['revision']):raise ValueError('Prior screening basis changed')
                else:
                    raw=subprocess.run([str(a.ffmpeg),'-v','error','-i',r['path'],'-f','f32le','-ar','16000','-ac','1','pipe:1'],check=True,capture_output=True)
                    segments,_=model.transcribe(np.frombuffer(raw.stdout,dtype='<f4'),**decoding)
                    record={'unit_id':u['id'],'audio_sha256':r['sha256'],'expected_text':u['caption'],
                      'asr_transcript':' '.join(s.text.strip() for s in segments),'decoding':decoding,
                      'model_revision':v['revision'],'native_listening_passed':False}
                    save_json(target,record)
                records[u['id']]=record;print('CONTEXT_PROGRESS_SCREENED',len(records),len(groups),flush=True)
            if len(records)<len(groups):time.sleep(5)
        validate(m)
        save_json(ROOT/'content-screening.private.json',{'results':[records[u['id']] for u in groups],'native_listening_passed':False})
        print('CONTEXT_PROGRESS_SCREENING_COMPLETE',flush=True)


if __name__=='__main__':main()
