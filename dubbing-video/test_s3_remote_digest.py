import hashlib
import io
import unittest
from unittest.mock import patch
from upload_review_video_s3 import remote_digest,parallel_remote_digest
import threading


class RemoteDigestTests(unittest.TestCase):
    def test_broken_stream_retries_range_without_hashing_partial_bytes(self):
        payload = b'a'*(5*1024**2)+b'last-range'
        class Broken(io.BytesIO):
            def read(self, *args): raise OSError('connection interrupted')
        class Fake:
            def __init__(self): self.calls=[]; self.streams=[]
            def get_object(self, **kw):
                self.calls.append(kw['Range']); start,end=map(int,kw['Range'][6:].split('-'))
                body=Broken() if len(self.calls)==1 else io.BytesIO(payload[start:end+1])
                self.streams.append(body)
                return {'Body':body,'ContentRange':f'bytes {start}-{end}/{len(payload)}'}
        client=Fake()
        with patch('upload_review_video_s3.time.sleep'):
            self.assertEqual(remote_digest(client,'bucket','key',len(payload)),hashlib.sha256(payload).hexdigest())
        self.assertEqual(client.calls[0],client.calls[1]);self.assertEqual(len(client.calls),3)
        self.assertTrue(all(s.closed for s in client.streams))

    def test_partial_or_wrong_range_is_rejected(self):
        class Fake:
            def get_object(self,**kw): return {'Body':io.BytesIO(b'partial'),'ContentRange':'bytes 0-9/10'}
        with patch('upload_review_video_s3.time.sleep'), self.assertRaises(RuntimeError):
            remote_digest(Fake(),'bucket','key',10)

    def test_parallel_ranges_hash_in_order_and_retry_only_failed_range(self):
        payload=b'a'*(1024**2)+b'b'*(1024**2)+b'last';lock=threading.Lock()
        calls={};streams=[]
        class Broken(io.BytesIO):
            def read(self,*args):raise OSError('broken stream')
        class Fake:
            def get_object(self,**kw):
                start,end=map(int,kw['Range'][6:].split('-'))
                with lock:
                    calls[start]=calls.get(start,0)+1
                    body=Broken() if start==1024**2 and calls[start]==1 else io.BytesIO(payload[start:end+1])
                    streams.append(body)
                return {'Body':body,'ContentRange':f'bytes {start}-{end}/{len(payload)}'}
        with patch('upload_review_video_s3.time.sleep'):
            self.assertEqual(parallel_remote_digest(Fake(),'bucket','key',len(payload)),hashlib.sha256(payload).hexdigest())
        self.assertEqual(calls,{0:1,1024**2:2,2*1024**2:1});self.assertTrue(all(s.closed for s in streams))


if __name__ == '__main__': unittest.main()
