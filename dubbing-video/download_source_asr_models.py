"""Download public ASR weights in resumable ranges, pinned to official repository hashes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import time

import requests
from process_lock import process_lock
from translate import read_json,save_json

ROOT=Path('output/tools/source-asr-models')


def download(name,range_step_mib=1):
    if range_step_mib not in (1,8):raise ValueError('Range step must be 1 or 8 MiB')
    folder=ROOT/name;folder.mkdir(parents=True,exist_ok=True)
    repo='Systran/faster-whisper-'+name
    marker=folder/'official-source.json'
    if marker.exists():meta=read_json(marker)
    else:
        response=requests.get('https://huggingface.co/api/models/'+repo,params={'blobs':'true'},timeout=30)
        response.raise_for_status();data=response.json()
        meta={'repo':repo,'revision':data['sha'],'siblings':data['siblings']}
        save_json(marker,meta)
    if meta['repo']!=repo or len(meta['revision'])!=40:raise ValueError('Unexpected model repository')
    for entry in meta['siblings']:
        filename=entry['rfilename']
        if filename not in ('model.bin','config.json','tokenizer.json','vocabulary.txt','vocabulary.json','preprocessor_config.json'):continue
        url='https://huggingface.co/'+repo+'/resolve/'+meta['revision']+'/'+filename
        target=folder/filename
        if filename=='model.bin':
            expected=entry['lfs']['sha256'];size=entry['lfs']['size'];chunk=8*1024**2
            parts=folder/'parts';parts.mkdir(exist_ok=True)
            def fetch(start):
                end=min(start+chunk,size)-1;piece=parts/f'{start:012}.bin'
                if piece.exists() and piece.stat().st_size==end-start+1:return piece
                for attempt in range(5):
                    http_status=None;substart=start
                    try:
                        step=range_step_mib*1024**2;blocks=[]
                        for substart in range(start,end+1,step):
                            subend=min(end,substart+step-1)
                            tail=folder/'tail-pieces'/f'{substart:012}.bin'
                            if step<chunk and tail.exists() and tail.stat().st_size==subend-substart+1:
                                block=tail.read_bytes()
                            else:
                                with requests.get(url,params={'download':'true','range_part':f'{substart}-{subend}'},
                                     headers={'Range':f'bytes={substart}-{subend}'},stream=True,timeout=(15,30)) as r:
                                    http_status=r.status_code
                                    if r.status_code!=206 or r.headers.get('Content-Range')!=f'bytes {substart}-{subend}/{size}':
                                        raise ValueError('Unexpected model range response')
                                    block=r.raw.read(subend-substart+1)
                                    if len(block)!=subend-substart+1:raise ValueError('Incomplete model range')
                                if step<chunk:
                                    tail.parent.mkdir(exist_ok=True);tail.write_bytes(block)
                            blocks.append(block)
                        data=b''.join(blocks)
                        temporary=piece.with_suffix('.part');temporary.write_bytes(data);temporary.replace(piece)
                        print('MODEL_PART',name,start,len(data),flush=True);return piece
                    except Exception as exc:
                        print('MODEL_RANGE_RETRY',name,start,substart,attempt+1,type(exc).__name__,http_status,flush=True)
                        if attempt==4:raise RuntimeError('Public model range download failed') from None
                        time.sleep(2**attempt)
            if not target.exists():
                with ThreadPoolExecutor(max_workers=8) as pool:pieces=list(pool.map(fetch,range(0,size,chunk)))
                temporary=target.with_suffix('.assembling');h=hashlib.sha256()
                with temporary.open('wb') as out:
                    for piece in pieces:
                        data=piece.read_bytes();h.update(data);out.write(data)
                if temporary.stat().st_size!=size or h.hexdigest()!=expected:raise ValueError('Official model SHA256 mismatch')
                temporary.replace(target)
            h=hashlib.sha256()
            with target.open('rb') as stream:
                for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
            if target.stat().st_size!=size or h.hexdigest()!=expected:raise ValueError('Existing model differs from official SHA256')
        else:
            if not target.exists():
                response=requests.get(url,timeout=30);response.raise_for_status();target.write_bytes(response.content)
            data=target.read_bytes();oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if oid!=entry['blobId']:raise ValueError('Model configuration differs from official Git object')
    if not (folder/'model.bin').exists():raise ValueError('Missing official model binary')
    save_json(folder/'verified.json',{'repo':repo,'revision':meta['revision'],'official_hashes_verified':True})
    print('MODEL_VERIFIED',name,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--models',nargs='+',default=['small.en','medium.en'],choices=['small.en','medium.en'])
    args=p.parse_args();ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(ROOT/'download.lock',timeout=0):
        for name in args.models:download(name)
