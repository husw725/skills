"""Windows multipart upload for the three explicitly scoped review candidates."""
import argparse
import hashlib
from pathlib import Path
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dub_episode import digest
from process_lock import process_lock
from translate import read_json, save_json


def remote_digest(s3, bucket, key, size):
    """Read every byte in bounded ranges; a broken stream retries only that range."""
    h = hashlib.sha256()
    for start in range(0, size, 5*1024**2):
        end = min(size-1, start+5*1024**2-1)
        for attempt in range(3):
            body = None
            try:
                response = s3.get_object(Bucket=bucket, Key=key, Range=f'bytes={start}-{end}')
                body = response['Body']; block = body.read(end-start+2)
                if (response.get('ContentRange') != f'bytes {start}-{end}/{size}'
                        or len(block) != end-start+1):
                    raise ValueError('Incomplete remote range')
                break
            except Exception:
                if attempt == 2: raise RuntimeError('Remote range verification failed') from None
                time.sleep(2**attempt)
            finally:
                if body is not None: body.close()
        h.update(block)
        print('VERIFIED_MIB', round((end+1)/1024**2, 1), flush=True)
    return h.hexdigest()


def parallel_remote_digest(s3,bucket,key,size):
    """Bounded four-range readback; hash every byte in order with smaller retries."""
    chunk=1024**2
    def fetch(start):
        end=min(size-1,start+chunk-1)
        for attempt in range(3):
            body=None
            try:
                response=s3.get_object(Bucket=bucket,Key=key,Range=f'bytes={start}-{end}')
                body=response['Body'];data=body.read(end-start+2)
                if response.get('ContentRange')!=f'bytes {start}-{end}/{size}' or len(data)!=end-start+1:
                    raise ValueError('Incomplete remote range')
                return data
            except Exception:
                if attempt==2:raise RuntimeError('Remote range verification failed') from None
                time.sleep(2**attempt)
            finally:
                if body is not None:body.close()
    h=hashlib.sha256();starts=iter(range(0,size,chunk));complete=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending=deque(pool.submit(fetch,start) for start in __import__('itertools').islice(starts,4))
        while pending:
            data=pending.popleft().result();h.update(data);complete+=len(data)
            print('VERIFIED_MIB',round(complete/1024**2,1),flush=True)
            start=next(starts,None)
            if start is not None:pending.append(pool.submit(fetch,start))
    return h.hexdigest()


def upload(episode, version, config):
    permitted = {(2, 3): ('feedback-v3', 'Carmilla_EP02_pt-BR_feedback_v3.mp4', 'feedback-ep02-v3'),
                 (7, 2): ('diagnostic-v2', 'Carmilla_EP07_pt-BR_diagnostic_v2.mp4', 'diagnostic-ep07-v2'),
                 (29, 2): ('diagnostic-v2', 'Carmilla_EP29_pt-BR_diagnostic_v2.mp4', 'diagnostic-ep29-v2')}
    if (episode, version) not in permitted:
        raise ValueError('Upload outside requested review scope')
    subdir, filename, receipt_name = permitted[(episode, version)]
    root = Path(f'output/drama-01/episode-{episode:02}')/subdir
    report = read_json(root/'render-report.json')
    video = root/filename
    sha = digest(video)
    if report['episode'] != episode or sha != report['output_sha256'] or not report['video_payload_identical']:
        raise ValueError('Video verification required')
    cfg = read_json(config)
    bucket = cfg.get('bucket')
    prefix = cfg.get('prefix', '').strip('/')
    if bucket != 'starlitshorts' or prefix != 'aigc/drama/dubbing-video/carmilla-20261009':
        raise ValueError('Use the existing approved Carmilla storage prefix')
    import boto3
    from botocore.config import Config
    from boto3.s3.transfer import TransferConfig
    kwargs = {}
    if cfg.get('ak') and cfg.get('sk'):
        kwargs = {'aws_access_key_id': cfg['ak'], 'aws_secret_access_key': cfg['sk']}
    elif boto3.Session().get_credentials() is None:
        raise ValueError('AWS credentials not configured')
    if cfg.get('session_token'):
        kwargs['aws_session_token'] = cfg['session_token']
    s3 = boto3.client('s3', region_name=cfg.get('region', 'us-east-1'),
                      config=Config(connect_timeout=15, read_timeout=60,
                                    retries={'max_attempts': 3, 'mode': 'standard'}), **kwargs)
    folder = Path('output/review-publication/148/Carmilla')/receipt_name
    folder.mkdir(parents=True, exist_ok=True)
    with process_lock(folder/'publish.lock', timeout=0):
        receipt_path = folder/'upload.private.json'
        if receipt_path.exists():
            existing = read_json(receipt_path)
            if existing.get('sha256') != sha:
                raise ValueError('Existing upload receipt differs; no overwrite')
            print('UPLOAD_RECEIPT_REUSED', episode, version, flush=True)
            return
        if list(folder.glob('version-submission*')) or (folder/'publication-result.json').exists():
            raise ValueError('Version submission exists; do not change uploaded URL')
        key = prefix+'/review-revisions/'+video.stem+'-'+sha[:12]+'.mp4'
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
        except s3.exceptions.ClientError as exc:
            if str(exc.response['Error']['Code']) not in ('404', 'NoSuchKey', 'NotFound'):
                raise RuntimeError('S3 object check failed; details omitted') from None
            head = None
        if head is not None and (head.get('Metadata', {}).get('sha256') != sha or head['ContentLength'] != video.stat().st_size):
            raise ValueError('Existing S3 object differs; no overwrite')
        if head is None:
            transferred = [0, time.time()]
            import threading
            lock = threading.Lock()
            def progress(n):
                with lock:
                    transferred[0] += n
                    if time.time()-transferred[1] > 10:
                        print('UPLOADED_MIB', round(transferred[0]/1024**2, 1), flush=True)
                        transferred[1] = time.time()
            s3.upload_file(str(video), bucket, key,
                           ExtraArgs={'ContentType': 'video/mp4', 'Metadata': {'sha256': sha}},
                           Config=TransferConfig(multipart_threshold=5*1024**2,
                                                 multipart_chunksize=5*1024**2, max_concurrency=3),
                           Callback=progress)
        head = s3.head_object(Bucket=bucket, Key=key)
        if head['ContentLength'] != video.stat().st_size or head.get('Metadata', {}).get('sha256') != sha:
            raise ValueError('S3 upload metadata mismatch')
        if remote_digest(s3, bucket, key, head['ContentLength']) != sha:
            raise ValueError('S3 remote content SHA mismatch')
        url = f'https://{bucket}.s3.amazonaws.com/{key}'
        import requests
        if requests.head(url, timeout=20).status_code != 200:
            raise ValueError('Review video is not publicly readable')
        save_json(folder/'upload.private.json', {'url': url, 'sha256': sha, 'bytes': video.stat().st_size,
                                               'remote_sha256_verified': True})
        print('S3_VERIFIED', episode, version, url, flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--episode', required=True, type=int)
    p.add_argument('--version', required=True, type=int)
    p.add_argument('--config', required=True, type=Path)
    a = p.parse_args()
    if sys.platform != 'win32':
        p.error('Business uploads are Windows-only')
    try:
        upload(a.episode, a.version, a.config)
    except Exception as exc:
        print('UPLOAD_STOPPED', type(exc).__name__, flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
