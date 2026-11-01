import unittest
from pipeline_source_additions import checked_words,apply


class ActualSourceWordsTests(unittest.TestCase):
    def setUp(self):
        self.report={'segments':[{'words':[dict(word='Tieni',start=1.,end=1.3),
                                          dict(word='alta',start=1.3,end=1.6),
                                          dict(word='la',start=1.6,end=1.8),
                                          dict(word='guardia.',start=1.8,end=2.1)]}]}

    def test_complete_actual_source_span_is_kept(self):
        out=checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',.95,2.15)
        self.assertEqual(len(out),4)

    def test_script_only_word_insertion_or_partial_window_is_rejected(self):
        with self.assertRaises(ValueError):checked_words(self.report,[0,1,2,3],'Tieni alta la guardia forever.',.95,2.15)
        with self.assertRaises(ValueError):checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',1.2,2.15)
        with self.assertRaises(ValueError):checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',.95,2.)

    def test_noncontiguous_duplicate_and_out_of_range_source_indices_rejected(self):
        for indices in [[0,2],[0,1,1],[0,1,2,3,4],[-1,0],[],[True,1]]:
            with self.subTest(indices=indices),self.assertRaises(ValueError):
                checked_words(self.report,indices,'Tieni alta la guardia.',.95,2.15)

    def test_internal_word_outside_window_and_nonfinite_times_are_rejected(self):
        words=self.report['segments'][0]['words']
        words[1]['end']=10.
        with self.assertRaises(ValueError):checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',.95,2.15)
        words[1]['end']=float('nan')
        with self.assertRaises(ValueError):checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',.95,2.15)
        words[1]['end']=True
        with self.assertRaises(ValueError):checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',.95,2.15)

    def test_no_addition_plan_preserves_existing_inputs(self):
        rows=[{'id':'original'}];candidate={'cues':[]};inputs={}
        out,translated=apply(rows,candidate,{}, {}, {}, inputs)
        self.assertIs(out,rows);self.assertIs(translated,candidate);self.assertEqual(inputs,{})

    def test_same_phrase_at_another_location_cannot_replace_frozen_source(self):
        words=self.report['segments'][0]['words']
        words.extend([{**w,'start':w['start']+10,'end':w['end']+10} for w in list(words)])
        checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',1.,2.1,[1.,2.1])
        with self.assertRaises(ValueError):
            checked_words(self.report,[4,5,6,7],'Tieni alta la guardia.',11.,12.1,[1.,2.1])
        with self.assertRaises(ValueError):
            checked_words(self.report,[0,1,2,3],'Tieni alta la guardia.',.95,2.15,[1.,2.1])


if __name__=='__main__':unittest.main()
