import tempfile,unittest
from pathlib import Path
from prepare_drama_assets import asset_scope,download

class PreparationTests(unittest.TestCase):
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
