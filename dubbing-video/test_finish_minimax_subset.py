import unittest
from finish_minimax_subset import subset


class SubsetTests(unittest.TestCase):
    def setUp(self):
        self.master={'groups':[dict(id='a',cache_key='one',request={'model':'speech-2.8-hd','text':'unchanged'}),
                               dict(id='b',cache_key='two',request={'model':'sonic-3.6','text':'pending'})]}

    def test_subset_keeps_original_request_and_excludes_unknown_provider(self):
        out=subset(self.master,['a'])
        self.assertEqual(out['groups'],[self.master['groups'][0]])
        self.assertEqual(out['max_new_tts'],1)
        self.assertEqual(len(self.master['groups']),2)

    def test_unknown_id_or_cartesia_cannot_be_submitted(self):
        for ids in [['missing'],['b'],[],['a','a']]:
            with self.subTest(ids=ids),self.assertRaises(ValueError):subset(self.master,ids)


if __name__=='__main__':unittest.main()
