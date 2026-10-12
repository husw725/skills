import tempfile,unittest
from unittest.mock import Mock,patch
from pathlib import Path
from prepare_drama_assets import asset_scope,download

class PreparationTests(unittest.TestCase):
 def test_bounded_range_resume_keeps_existing_prefix(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'source';part=p.with_name('source.download.part');part.write_bytes(b'abc')
   response=Mock();response.status_code=206;response.headers={'Content-Range':'bytes 3-6/7'}
   response.iter_content.return_value=[b'defg'];response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
   session=Mock();session.get.return_value=response
   with patch('prepare_drama_assets.requests.Session',return_value=session):
    result=download({'bytes':7},'https://example.invalid/source',p)
   self.assertEqual(p.read_bytes(),b'abcdefg');self.assertTrue(result['download_verified'])
   self.assertEqual(session.get.call_args.kwargs['headers']['Range'],'bytes=3-6')
 def test_wrong_resumed_range_preserves_partial(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'source';part=p.with_name('source.download.part');part.write_bytes(b'abc')
   response=Mock();response.status_code=206;response.headers={'Content-Range':'bytes 0-6/7'}
   response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
   session=Mock();session.get.return_value=response
   with patch('prepare_drama_assets.requests.Session',return_value=session):
    with self.assertRaises(ValueError):download({'bytes':7},'https://example.invalid/source',p)
   self.assertEqual(part.read_bytes(),b'abc');self.assertFalse(p.exists())
 def test_leading_zero_episode_and_source_kind(self):
  self.assertEqual(asset_scope({'name':'Lady_EP010.srt','path':'/share/纯字幕/Lady_EP010.srt'}),(10,'subtitle'))
 def test_unsafe_asset_name_and_duplicate_source_versions_are_not_assumed(self):
  with self.assertRaises(ValueError):asset_scope({'name':'../Lady_EP01.srt','path':'/share/纯字幕/file'})
  with self.assertRaises(ValueError):asset_scope({'name':'Lady_EP31.srt','path':'/share/纯字幕/file'})
 def test_existing_download_is_verified_and_changed_file_is_preserved(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'source';p.write_bytes(b'original');r=download({'bytes':8},'unused',p)
   self.assertTrue(r['download_verified']);p.write_bytes(b'changed!')
   with self.assertRaises(ValueError):download({'bytes':8},'unused',p,r)
   self.assertEqual(p.read_bytes(),b'changed!')

if __name__=='__main__':unittest.main()
