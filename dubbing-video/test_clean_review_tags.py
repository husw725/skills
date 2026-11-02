import unittest
from clean_review_film_tags import patch, unchanged


class FilmTagTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(projectId=148, gateType='FINAL_CUT', assetId=7,
                        name='Carmilla | synthetic test', tags=['Carmilla','synthetic-hash'],
                        url='https://example.invalid/synthetic.mp4',version=1,note='preserve')

    def test_only_four_targeting_and_tag_fields_are_sent(self):
        self.assertEqual(patch(self.row),dict(projectId=148,gateType='FINAL_CUT',assetId=7,tags=['Carmilla']))
        self.assertEqual(self.row['tags'],['Carmilla','synthetic-hash'])

    def test_unknown_film_other_project_and_document_rejected(self):
        for change in [dict(name='Unknown | sample'),dict(projectId=100),dict(gateType='DOCUMENT')]:
            with self.subTest(change=change),self.assertRaises(ValueError):patch({**self.row,**change})

    def test_content_or_version_change_is_detected(self):
        self.assertTrue(unchanged(self.row,{**self.row,'tags':['Carmilla'],'updatedAt':'new'}))
        for change in [dict(url='https://example.invalid/different.mp4'),dict(version=2),dict(note='changed')]:
            with self.subTest(change=change):self.assertFalse(unchanged(self.row,{**self.row,**change}))


if __name__=='__main__':unittest.main()
