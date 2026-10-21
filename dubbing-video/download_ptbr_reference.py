"""Download a small attributed pt-BR FLEURS listening reference on Windows."""
import hashlib
import io
import sys
import tarfile
import time
from pathlib import Path
import requests
import soundfile
from process_lock import process_lock
from translate import read_json,save_json

ROOT=Path('input/pt-br-reference/fleurs-20261021')
BASE='https://huggingface.co/datasets/google/fleurs/resolve/main/'
LIMIT=64*1024*1024


class BoundedStream:
 def __init__(self,raw):self.raw=raw;self.used=0
 def read(self,size=-1):
  if self.used>=LIMIT:raise ValueError('Reference download byte budget reached')
  data=self.raw.read(min(size if size>=0 else 65536,LIMIT-self.used));self.used+=len(data);return data


def main():
 if sys.platform!='win32':raise ValueError('Download production reference on Windows')
 ROOT.mkdir(parents=True,exist_ok=True)
 with process_lock(ROOT/'download.lock',timeout=0):
  manifest_path=ROOT/'manifest.private.json'
  if manifest_path.exists():
   m=read_json(manifest_path)
   for sample in m['samples']:
    if hashlib.sha256((ROOT/sample['filename']).read_bytes()).hexdigest()!=sample['sha256']:raise ValueError('Existing reference changed')
   print('REFERENCE_CACHE_VERIFIED',len(m['samples']),round(sum(s['duration_seconds'] for s in m['samples']),2),flush=True);return
  with requests.Session() as session:
   for name,relative in [('README.source.md','README.md'),('test.source.tsv','data/pt_br/test.tsv')]:
    r=session.get(BASE+relative,timeout=45);r.raise_for_status()
    if len(r.content)>2*1024*1024:raise ValueError('Unexpected reference metadata size')
    (ROOT/name).write_bytes(r.content)
   readme=(ROOT/'README.source.md').read_text(encoding='utf-8')
   if 'cc-by-4.0' not in readme or 'pt_br' not in readme:raise ValueError('Expected explicit pt-BR/CC BY source')
   metadata={}
   for line in (ROOT/'test.source.tsv').read_text(encoding='utf-8').splitlines():
    cols=line.split('\t')
    for col in cols:
     if col.lower().endswith(('.wav','.flac')):metadata[Path(col).name]=cols
   samples=[]
   with session.get(BASE+'data/pt_br/audio/test.tar.gz',stream=True,timeout=(20,60)) as response:
    response.raise_for_status();limited=BoundedStream(response.raw)
    with tarfile.open(fileobj=limited,mode='r|gz') as archive:
     for member in archive:
      if not member.isfile() or not member.name.lower().endswith(('.wav','.flac')):continue
      name=Path(member.name).name
      if name not in metadata:raise ValueError('Audio lacks original text metadata')
      if not 0<member.size<=8*1024*1024:raise ValueError('Unexpected reference file size')
      body=archive.extractfile(member).read(member.size+1)
      if len(body)!=member.size:raise ValueError('Incomplete reference audio')
      info=soundfile.info(io.BytesIO(body))
      if info.samplerate!=16000 or info.channels!=1 or not 1<=info.duration<=60:raise ValueError('Unexpected reference audio shape')
      path=ROOT/name
      if path.exists() and path.read_bytes()!=body:raise ValueError('Prior partial reference differs')
      path.write_bytes(body)
      samples.append({'filename':name,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),
       'duration_seconds':info.duration,'sample_rate':info.samplerate,'source_metadata_columns':metadata[name]})
      if len(samples)>=12:break
   if len(samples)!=12:raise ValueError('Incomplete bounded listening reference')
   manifest={'dataset':'Google FLEURS','locale':'pt_br','split':'test','license':'CC BY 4.0',
    'source':'https://huggingface.co/datasets/google/fleurs','downloaded_at':time.time(),
    'compressed_bytes_read':limited.used,'samples':samples,'purpose':'Listening/pronunciation comparison only; read speech, not acted dialogue.',
    'voice_cloning_authorized':False,'model_training_performed':False,'native_listening_performed':False,
    'metadata_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['README.source.md','test.source.tsv']}}
   save_json(manifest_path,manifest)
   print('REFERENCE_DOWNLOAD_VERIFIED',len(samples),round(sum(s['duration_seconds'] for s in samples),2),'SECONDS',limited.used,'COMPRESSED_BYTES',flush=True)


if __name__=='__main__':main()
