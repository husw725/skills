import copy
import tempfile
from pathlib import Path
from dub_episode import digest
import unittest
from assemble_background_edits import layout, assemble


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.spec={'duration':2,'segments':[dict(target_start=0,target_end=1,source_start=.2,source={'path':'synthetic','sha256':'x'},basis='same cut'),dict(target_start=1,target_end=2,source_start=4,source={'path':'synthetic','sha256':'x'},basis='declared switch')]}

    def test_sample_partition(self):
        total,segments=layout(self.spec);self.assertEqual(total,96000);self.assertEqual([(x[1],x[2],x[3])for x in segments],[(0,48000,9600),(48000,96000,192000)])

    def test_gap_overlap_and_missing_tail_rejected(self):
        for start in [.99,1.01]:
            other=copy.deepcopy(self.spec);other['segments'][1]['target_start']=start
            with self.assertRaises(ValueError):layout(other)
        self.spec['segments'].pop()
        with self.assertRaises(ValueError):layout(self.spec)

    def test_nonfinite_negative_and_bool_rejected(self):
        for value in [float('nan'),float('inf'),-1,True]:
            other=copy.deepcopy(self.spec);other['segments'][0]['source_start']=value
            with self.assertRaises(ValueError):layout(other)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        try:
            import numpy as np
            import soundfile as sf
            import scipy.signal
        except ImportError:
            self.skipTest('Audio dependencies unavailable here; run on media worker')
        self.np,self.sf=np,sf
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'source.wav'
        sf.write(self.path,np.full((44100*2,2),.125,dtype='float32'),44100,subtype='FLOAT')
        self.sha=digest(self.path)
        self.spec={'episode':1,'duration':2,'edge_fade_ms':8,'segments':[
            dict(target_start=0,target_end=1,source_start=0,source={'path':str(self.path),'sha256':self.sha},basis='same cut'),
            dict(target_start=1,target_end=2,source_start=1,source={'path':str(self.path),'sha256':self.sha},basis='declared switch')]}

    def test_actual_assembly_preserves_source_and_sample_timeline(self):
        proof,receipt=assemble(self.spec,self.root/'out');data,rate=self.sf.read(proof['output'])
        self.assertEqual(data.shape,(96000,2));self.assertEqual(rate,48000)
        self.assertEqual(digest(self.path),self.sha);self.assertEqual(digest(proof['output']),proof['output_sha256'])
        self.assertFalse(proof['background_listening_passed']);self.assertEqual(proof['explicit_tail_padding'],[])
        self.assertAlmostEqual(data[1000,0],.125,places=4)
        self.assertEqual(data[47999,0],0);self.assertEqual(data[48000,0],0)
        self.assertTrue(receipt.exists())

    def test_short_tail_requires_explicit_policy_and_no_long_pad(self):
        self.spec['segments'][-1]['source_start']=1.02
        with self.assertRaisesRegex(ValueError,'tail'):assemble(self.spec,self.root/'out')
        self.spec['segments'][-1]['tail_pad_seconds']=.025
        proof,_=assemble(self.spec,self.root/'out')
        self.assertAlmostEqual(proof['explicit_tail_padding'][0]['seconds'],.02,places=5)
        data,_=self.sf.read(proof['output'])
        boundary=round(proof['explicit_tail_padding'][0]['target_start']*48000)
        self.assertEqual(data[boundary-1,0],0)
        self.assertTrue(self.np.all(data[boundary:]==0))
        self.spec['segments'][-1]['source_start']=1.1
        with self.assertRaisesRegex(ValueError,'tail'):assemble(self.spec,self.root/'out')


if __name__=='__main__':unittest.main()
