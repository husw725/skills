import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from dub_episode import digest
import numpy as np
from render_comment_repairs import RATE,assemble,envelope,copy_subtitle

class CommentRepairMediaTests(unittest.TestCase):
 def test_overlapping_ducks_use_lowest_gain_without_multiplication(self):
  e=envelope(1000,[dict(start=2,end=6,gain=.5,attack=1,release=1),dict(start=4,end=8,gain=.4,attack=0,release=0)],100)
  self.assertAlmostEqual(float(e[450]),.4);self.assertAlmostEqual(float(e[300]),.5);self.assertEqual(float(e[0]),1);self.assertEqual(float(e[900]),1)
 def test_attack_release_and_short_gap_are_continuous(self):
  e=envelope(1000,[dict(start=2,end=4,gain=.25,attack=1,release=1)],100)
  self.assertAlmostEqual(float(e[150]),.625);self.assertAlmostEqual(float(e[450]),.625);self.assertAlmostEqual(float(e[250]),.25)
 def test_dialogue_assembly_uses_exact_placement_and_gain(self):
  groups=[dict(id='a',start=0,gain=1),dict(id='b',start=2/RATE,gain=.5)]
  out=assemble(groups,6,lambda g:np.array([.1,.2],np.float32))
  np.testing.assert_allclose(out,[.1,.2,.05,.1,0,0])
 def test_no_speech_truncation_or_invalid_values(self):
  with self.assertRaisesRegex(ValueError,'exceeds'):assemble([dict(start=0)],1,lambda _:np.ones(2))
  for value in [True,float('nan'),-1]:
   with self.assertRaises(ValueError):envelope(100,[dict(start=0,end=.5,gain=value,attack=0,release=0)],100)
 def test_stereo_bed_multiplies_both_channels_equally(self):
  bed=np.array([[.2,.4]]*100,dtype=np.float32);gain=envelope(100,[dict(start=0,end=1,gain=.5,attack=0,release=0)],100)
  np.testing.assert_allclose(bed*gain[:,None],np.array([[.1,.2]]*100),atol=1e-7)

 def test_corrupt_subtitle_copy_is_rejected_while_source_remains_approved(self):
  with tempfile.TemporaryDirectory() as folder:
   source=Path(folder)/'source.srt';target=Path(folder)/'target.srt';source.write_bytes(b'synthetic timed subtitle')
   expected=digest(source);copy_subtitle(source,target,expected);self.assertEqual(source.read_bytes(),target.read_bytes())
   with patch('render_comment_repairs.shutil.copyfile',side_effect=lambda s,t:Path(t).write_bytes(b'wrong copy')):
    with self.assertRaisesRegex(ValueError,'Copied subtitle differs'):copy_subtitle(source,target,expected)
   self.assertEqual(digest(source),expected)

if __name__=='__main__':unittest.main()
