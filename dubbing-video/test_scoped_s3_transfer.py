import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch,MagicMock
from scoped_s3_transfer import reserve,upload_reserved,verify_public


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.video=self.root/'test.mp4';self.video.write_bytes(b'synthetic video')
        self.sha=hashlib.sha256(self.video.read_bytes()).hexdigest();self.receipt=self.root/'ledger.json';self.ledger={'uploads':{}}
        self.c=Mock();self.c.call.return_value='https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/new.mp4?signature=synthetic'
    def head(self):return {'ContentLength':self.video.stat().st_size,'ChecksumType':'FULL_OBJECT','ChecksumSHA256':base64.b64encode(bytes.fromhex(self.sha)).decode()}
    def test_reuses_reservation_without_new_url(self):
        item,key=reserve(self.c,self.video,self.ledger,self.receipt,set());reserve(self.c,self.video,self.ledger,self.receipt,set())
        self.assertEqual(self.c.call.call_count,1);self.assertTrue(key.startswith('aigc/uploads/mcp/review/'))
    def test_protected_key_prevents_upload(self):
        with self.assertRaisesRegex(ValueError,'protected'):reserve(self.c,self.video,self.ledger,self.receipt,{'/aigc/uploads/mcp/review/new.mp4'})
    def test_existing_verified_checksum_skips_upload(self):
        item,key=reserve(self.c,self.video,self.ledger,self.receipt,set());s3=Mock();s3.head_object.return_value=self.head()
        upload_reserved(s3,self.video,self.ledger,self.receipt,item,key);s3.upload_file.assert_not_called();self.assertEqual(item['status'],'verified')
    def test_existing_mismatch_never_overwritten(self):
        item,key=reserve(self.c,self.video,self.ledger,self.receipt,set());s3=Mock();s3.head_object.return_value={**self.head(),'ChecksumSHA256':'bad'}
        with self.assertRaises(ValueError):upload_reserved(s3,self.video,self.ledger,self.receipt,item,key)
        s3.upload_file.assert_not_called()
    def test_unknown_multipart_not_repeated_when_object_missing(self):
        item,key=reserve(self.c,self.video,self.ledger,self.receipt,set());item['aws_status']='started';s3=Mock();error=RuntimeError();error.response={'Error':{'Code':'404'}};s3.head_object.side_effect=error
        with self.assertRaisesRegex(ValueError,'unknown'):upload_reserved(s3,self.video,self.ledger,self.receipt,item,key)
        s3.upload_file.assert_not_called()

    def test_public_range_requires_real_media_prefix(self):
        http=MagicMock();response=http.get.return_value.__enter__.return_value
        response.status_code=206;response.headers={'Content-Range':f'bytes 0-14/15'}
        response.iter_content.return_value=[b'synthetic video']
        verify_public(http,self.video,'https://example.test/new')
        response.status_code=403
        with self.assertRaisesRegex(ValueError,'publicly'):verify_public(http,self.video,'https://example.test/new')
        response.status_code=206;response.iter_content.return_value=[b'wrong']
        with self.assertRaisesRegex(ValueError,'prefix'):verify_public(http,self.video,'https://example.test/new')


if __name__=='__main__':unittest.main()
