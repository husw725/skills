"""Multipart transfer of reserved Review objects; preserves existing object identities."""
from pathlib import Path
from urllib.parse import urlsplit,unquote

from dub_episode import digest
from pipeline_publish import object_key
from publish_season_candidates import verify_s3_checksum
from translate import save_json
from upload_review_video_s3 import parallel_remote_digest

BUCKET='starlitshorts'
PREFIX='aigc/uploads/mcp/review/'


def reserve(client,path,ledger,receipt,protected_keys):
    sha=digest(path);item=ledger['uploads'].get(sha)
    if item is None:
        ledger['uploads'][sha]={'status':'preparing_url','sha256':sha,'bytes':path.stat().st_size};save_json(receipt,ledger)
        signed=client.call('createFilePresignedUrl',{'originalFileName':path.name})
        u=urlsplit(signed)if isinstance(signed,str)else None
        if u is None or u.scheme!='https' or u.hostname!='starlitshorts.s3.amazonaws.com' or u.username or u.password:
            raise ValueError('Unexpected Review upload host')
        url=u._replace(query='',fragment='').geturl()
        item={'status':'upload_pending','sha256':sha,'bytes':path.stat().st_size,'signed_url':signed,'url':url}
        ledger['uploads'][sha]=item;save_json(receipt,ledger)
    if item.get('sha256')!=sha or item.get('bytes')!=path.stat().st_size or not item.get('url'):
        raise ValueError('Existing reservation uncertain or changed')
    u=urlsplit(item['url']);key=unquote(u.path).lstrip('/')
    if u.scheme!='https' or u.hostname!='starlitshorts.s3.amazonaws.com' or not key.startswith(PREFIX) or '..'in key.split('/'):
        raise ValueError('Reserved object outside the allowed Review prefix')
    if item['status']!='verified' and object_key(item['url'])in protected_keys:
        raise ValueError('Reserved object collides with protected source/history')
    return item,key


def upload_reserved(s3,path,ledger,receipt,item,key):
    from boto3.s3.transfer import TransferConfig
    sha=digest(path)
    if sha!=item['sha256'] or path.stat().st_size!=item['bytes']:
        raise ValueError('Frozen upload source changed')
    try:head=s3.head_object(Bucket=BUCKET,Key=key,ChecksumMode='ENABLED')
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code')not in ('404','NoSuchKey','NotFound'):raise RuntimeError('Authenticated object check failed')from None
        head=None
    method='authenticated_s3_sha256_checksum'
    if head is not None:
        if not verify_s3_checksum(path,sha,head):
            if (head.get('ContentLength')==item['bytes'] and not head.get('ChecksumSHA256')
                    and parallel_remote_digest(s3,BUCKET,key,item['bytes'])==sha):
                method='parallel_full_get_sha256_legacy_reserved_object'
            else:
                # Never overwrite on weak user metadata or size alone.
                raise ValueError('Reserved object exists without matching trusted SHA256 checksum; reconcile')
    else:
        if item.get('aws_status')=='started':
            raise ValueError('Previous multipart outcome unknown; reconcile before another upload')
        item['aws_status']='started';save_json(receipt,ledger)
        try:
            s3.upload_file(str(path),BUCKET,key,
                ExtraArgs={'ContentType':'video/mp4','Metadata':{'sha256':sha},'ChecksumAlgorithm':'SHA256'},
                Config=TransferConfig(multipart_threshold=5*1024**2,multipart_chunksize=5*1024**2,max_concurrency=8))
        except Exception:raise RuntimeError('Multipart outcome uncertain; reservation retained')from None
        head=s3.head_object(Bucket=BUCKET,Key=key,ChecksumMode='ENABLED')
        if not verify_s3_checksum(path,sha,head):raise ValueError('Server cryptographic checksum differs')
    item.update(status='verified',aws_status='verified',verification_method=method,
                aws_checksum_type=head.get('ChecksumType'),aws_checksum_sha256=head.get('ChecksumSHA256'))
    save_json(receipt,ledger)
    return item['url']


def client(config):
    import boto3
    from botocore.config import Config
    if config.get('bucket')!=BUCKET or config.get('prefix')!=PREFIX:
        raise ValueError('Unexpected storage scope')
    return boto3.client('s3',region_name='us-east-1',aws_access_key_id=config['ak'],aws_secret_access_key=config['sk'],
        config=Config(connect_timeout=15,read_timeout=120,retries={'max_attempts':3},proxies={},max_pool_connections=32))


def verify_public(http,path,url):
    size=path.stat().st_size;n=min(1024,size)
    with path.open('rb')as f:expected=f.read(n)
    with http.get(url,headers={'Range':f'bytes=0-{n-1}','Accept-Encoding':'identity'},
                  stream=True,timeout=30,allow_redirects=False)as response:
        if response.status_code==206:
            if response.headers.get('Content-Range')!=f'bytes 0-{n-1}/{size}':raise ValueError('Public object range differs')
        elif response.status_code==200:
            if response.headers.get('Content-Length')!=str(size):raise ValueError('Public object size differs')
        else:raise ValueError('Review object not publicly readable')
        prefix=bytearray()
        for part in response.iter_content(1024):
            prefix.extend(part)
            if len(prefix)>=n:break
        if bytes(prefix[:n])!=expected:raise ValueError('Public object prefix differs')
