import copy
import unittest
from export_review_editorial_edits import apply_edits


class ReviewedEditTests(unittest.TestCase):
    def setUp(self):
        self.rows=[dict(id='cue1',text='When she does.',start=1.001,end=2.002)]
        self.candidate=dict(cues=[dict(id='cue1',translation='Quando conseguir.')])
        self.edits=[dict(id='cue1',source_text='When she does.',baseline_translation='Quando conseguir.',translation='Quando agir.')]

    def test_immutable_baseline_and_source(self):
        before=copy.deepcopy((self.rows,self.candidate,self.edits))
        result=apply_edits(self.rows,self.candidate,self.edits)
        self.assertEqual(result['cues'][0]['translation'],'Quando agir.')
        self.assertEqual((self.rows,self.candidate,self.edits),before)

    def test_changed_source_or_baseline_is_rejected(self):
        for key in ('source_text','baseline_translation'):
            edits=copy.deepcopy(self.edits);edits[0][key]='different'
            with self.assertRaises(ValueError):apply_edits(self.rows,self.candidate,edits)

    def test_duplicate_or_empty_edit_is_rejected(self):
        with self.assertRaises(ValueError):apply_edits(self.rows,self.candidate,self.edits*2)
        edits=copy.deepcopy(self.edits);edits[0]['translation']=' '
        with self.assertRaises(ValueError):apply_edits(self.rows,self.candidate,edits)


if __name__=='__main__':unittest.main()
