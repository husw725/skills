import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
import pipeline_publish as publishing
import requests
from mflix_client import Mflix


class Response:
    status_code=200
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def iter_content(self,*args):yield self.body


class PublicationUploadTests(unittest.TestCase):
    def test_verified_upload_reuses_same_object_without_put(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'synthetic.mp4';path.write_bytes(b'synthetic artifact')
            client=Mock();client.call.return_value='https://example.s3.amazonaws.com/synthetic?signature=test'
            client.http.put.return_value.status_code=200
            client.http.get.side_effect=lambda *args,**kwargs:Response(path.read_bytes())
            ledger={'uploads':{},'items':{}};receipt=root/'ledger.json'
            first=publishing.upload(client,path,ledger,receipt)
            second=publishing.upload(client,path,ledger,receipt)
            self.assertEqual(first,second)
            self.assertEqual(client.call.call_count,1)
            self.assertEqual(client.http.put.call_count,1)
            self.assertEqual(client.http.get.call_count,2)

    def test_presign_rpc_connection_error_is_not_retried(self):
        client=Mflix.__new__(Mflix)
        client.counter=0;client.url='https://example.invalid/mcp';client.headers={};client.http=Mock()
        client.http.post.side_effect=requests.ConnectionError('synthetic connection loss')
        with self.assertRaises(RuntimeError):
            client.rpc('tools/call',{'name':'createFilePresignedUrl','arguments':{'originalFileName':'synthetic.mp4'}})
        self.assertEqual(client.http.post.call_count,1)

    def test_existing_asset_object_cannot_be_put_even_with_different_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'synthetic.mp4';path.write_bytes(b'synthetic artifact')
            client=Mock();client.call.return_value='https://example.s3.amazonaws.com/existing%20asset.mp4?signature=test'
            old={publishing.object_key('https://cdn.example.org/existing%20asset.mp4?old=signature')}
            with self.assertRaisesRegex(ValueError,'collides'):
                publishing.upload(client,path,{'uploads':{},'items':{}},root/'ledger.json',old)
            client.http.put.assert_not_called()

    def test_unknown_presign_outcome_does_not_allocate_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'synthetic.mp4';path.write_bytes(b'synthetic')
            client=Mock();client.call.side_effect=TimeoutError('unknown')
            ledger={'uploads':{},'items':{}};receipt=root/'ledger.json'
            with self.assertRaises(TimeoutError):publishing.upload(client,path,ledger,receipt)
            with self.assertRaises(ValueError):publishing.upload(client,path,ledger,receipt)
            self.assertEqual(client.call.call_count,1)
            client.http.put.assert_not_called()


if __name__=='__main__':unittest.main()
