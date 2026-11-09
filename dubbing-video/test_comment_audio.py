import unittest,numpy as np
from prepare_comment_audio import insert_pause,remove_quiet_interval
class PauseTests(unittest.TestCase):
 def test_retains_all_source_samples_exactly(self):
  a=np.r_[np.ones(1000)*.2,np.zeros(2000),np.ones(1000)*.3].astype(np.float32);out=insert_pause(a,2000,1000)
  np.testing.assert_array_equal(out[:2000],a[:2000]);np.testing.assert_array_equal(out[3000:],a[2000:]);self.assertTrue(np.all(out[2000:3000]==0))
 def test_remove_only_quiet_preserves_every_other_sample(self):
  a=np.r_[np.ones(1000)*.2,np.zeros(2000),np.ones(1000)*.3].astype(np.float32);out=remove_quiet_interval(a,1500,2500)
  np.testing.assert_array_equal(out,np.r_[a[:1500],a[2500:]])
  a[2000]=.1
  with self.assertRaises(ValueError):remove_quiet_interval(a,1500,2500)
 def test_rejects_invalid_source(self):
  for a in [np.array([0.,float('nan'),0.]),np.array([0.,float('inf'),0.]),np.zeros((4,2))]:
   with self.assertRaises(ValueError):insert_pause(a,1,1)
 def test_rejects_spoken_split_and_nonfinite_count(self):
  for cut,add in [(2000,1000),(0,1),(2,-1),(2,float('inf'))]:
   with self.assertRaises(ValueError):insert_pause(np.ones(4000,dtype=np.float32),cut,add)
if __name__=='__main__':unittest.main()
