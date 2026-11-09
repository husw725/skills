import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
from render_comment_repairs import reconcile_legacy_zero_tail,main
class RenderContinuityTests(unittest.TestCase):
 def test_only_short_all_zero_tail_can_be_removed(self):
  original=np.r_[np.ones(48000)*.2,np.zeros(2554)];a,b,n=reconcile_legacy_zero_tail(original,original.copy(),1.0)
  self.assertEqual(n,2554);np.testing.assert_array_equal(a,original[:48000]);np.testing.assert_array_equal(b,original[:48000])
  for value in [1e-9,.1]:
   x=original.copy();x[-1]=value
   with self.assertRaises(ValueError):reconcile_legacy_zero_tail(x,original,1.0)
  with self.assertRaises(ValueError):reconcile_legacy_zero_tail(np.zeros(54000),np.zeros(54000),1.0)
 def test_one_failed_episode_does_not_block_other_approved_rows(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);m=p/'manifest';m.write_text(json.dumps(dict(film='The Count of Monte Cristo',episodes=[dict(episode=i) for i in [1,2,3]])));a=p/'approval';a.write_text(json.dumps(dict(manifest_sha256=hashlib.sha256(m.read_bytes()).hexdigest(),technical_repair_render_approved=True)))
   def fake(row,*args):
    if row['episode']==2:raise ValueError('synthetic bad episode')
    return dict(status='candidate_rendered',report='synthetic',report_sha256='a'*64)
   argv=['render','--manifest',str(m),'--approval',str(a),'--output',str(p/'out'),'--ffmpeg','synthetic','--continue-on-error']
   with patch('sys.argv',argv),patch('sys.platform','win32'),patch('render_comment_repairs.render',side_effect=fake):
    with self.assertRaisesRegex(ValueError,'held'):main()
   state=json.loads((p/'out/progress.private.json').read_text());self.assertEqual(set(state['episodes']),{'1','3'});self.assertEqual(set(state['errors']),{'2'})
if __name__=='__main__':unittest.main()
