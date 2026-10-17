import json
from pathlib import Path
import tempfile
import unittest

from publish_season_candidates import append_version
from translate import read_json


class FakeReview:
    def __init__(self):
        self.rows=[{'projectId':148,'gateType':'FINAL_CUT','assetId':100,'version':1,
                    'name':'Carmilla | EP.01 | pt-BR','url':'https://example.test/old.mp4','tags':['Carmilla','pt-BR']}]
        self.writes=0;self.fail=None

    def call(self,name,args):
        if name=='getProjectReviewMaterials':return {'finalCutMaterials':[self.rows[-1]]}
        if name=='getReviewMaterialHistory':return list(self.rows)
        if name!='updateReviewMaterialVersion':raise AssertionError(name)
        self.writes+=1
        if self.fail=='before':raise RuntimeError('Network outcome uncertain')
        row={**args['material'],'assetId':100+self.writes,'version':len(self.rows)+1}
        self.rows.append(row)
        if self.fail=='after':raise RuntimeError('Response lost')
        return row


class SeasonPublicationTests(unittest.TestCase):
    def publish(self,client,root):
        return append_version(client,1,'https://example.test/new.mp4','abc123',60,root)

    def test_repeat_run_keeps_old_version_and_creates_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            c=FakeReview();root=Path(temp)
            self.assertEqual(self.publish(c,root)['version'],2)
            self.assertEqual(self.publish(c,root)['version'],2)
            self.assertEqual(c.writes,1)
            self.assertEqual(c.rows[0]['url'],'https://example.test/old.mp4')

    def test_lost_response_reconciles_without_duplicate_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            c=FakeReview();c.fail='after';root=Path(temp)
            with self.assertRaises(RuntimeError):self.publish(c,root)
            self.assertEqual(self.publish(c,root)['version'],2)
            self.assertEqual(c.writes,1)

    def test_unknown_outcome_without_visible_version_blocks_second_write(self):
        with tempfile.TemporaryDirectory() as temp:
            c=FakeReview();c.fail='before';root=Path(temp)
            with self.assertRaises(RuntimeError):self.publish(c,root)
            c.fail=None
            with self.assertRaises(RuntimeError):self.publish(c,root)
            self.assertEqual(c.writes,1)

    def test_wrong_scope_intent_is_rejected_before_first_bind_or_write(self):
        for key,value in [('projectId',999),('gateType','DOCUMENT'),('assetId',999)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as temp:
                c=FakeReview();root=Path(temp);c.fail='before'
                with self.assertRaises(RuntimeError):self.publish(c,root)
                p=root/'version-intent.private.json';intent=read_json(p);intent['material'][key]=value
                p.write_text(json.dumps(intent));(root/'version-input.json').unlink()
                c.fail=None
                with self.assertRaises(ValueError):self.publish(c,root)
                self.assertEqual(c.writes,1)


if __name__=='__main__':unittest.main()
