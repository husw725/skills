import copy
from pathlib import Path
import tempfile
import unittest
import hashlib
from unittest.mock import MagicMock
from publish_background_revisions import append_version,FILM,verify_subtitle


class FakeReview:
    def __init__(self):
        self.rows=[dict(projectId=148,assetId=3049,gateType='FINAL_CUT',name=FILM+' | EP01 | pt-BR | oldhash',url='https://example.test/old',version=1,tags=[FILM])]
        self.writes=0;self.fail=None
    def call(self,name,args):
        if name=='getReviewMaterialHistory':return copy.deepcopy(self.rows)
        assert name=='updateReviewMaterialVersion'
        self.writes+=1
        if self.fail=='before':raise RuntimeError('unknown')
        row={**args['material'],'assetId':4000,'version':2};self.rows.append(row)
        if self.fail=='after':raise RuntimeError('lost response')
        return row


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.client=FakeReview();self.row=dict(episode=1,old_video_asset_id=3049,old_video_url='https://example.test/old',video_sha256='a'*64,subtitle_asset_id=3050,subtitle_sha256='b'*64,duration=60,delivery_note='Declared edits pending professional review.')
    def run_publish(self):return append_version(self.client,self.row,'https://example.test/new',self.root)
    def test_repeat_uses_one_version_and_film_only_tag(self):
        first=self.run_publish();self.run_publish();self.assertEqual(self.client.writes,1)
        self.assertEqual(first['tags'],[FILM]);self.assertEqual(self.client.rows[0]['url'],'https://example.test/old')
    def test_lost_response_reconciles_without_resubmit(self):
        self.client.fail='after'
        with self.assertRaises(RuntimeError):self.run_publish()
        self.run_publish();self.assertEqual(self.client.writes,1)
    def test_unknown_without_visible_version_blocks(self):
        self.client.fail='before'
        with self.assertRaises(RuntimeError):self.run_publish()
        self.client.fail=None
        with self.assertRaises(RuntimeError):self.run_publish()
        self.assertEqual(self.client.writes,1)
    def test_wrong_episode_or_current_asset_blocks_write(self):
        self.row['episode']=2
        with self.assertRaises(ValueError):self.run_publish()
        self.assertEqual(self.client.writes,0)


class SubtitleTests(unittest.TestCase):
    def test_current_asset_and_full_content_required(self):
        body=b'synthetic srt';row=dict(episode=1,subtitle_asset_id=2,subtitle_url='https://example.test/srt',subtitle_sha256=hashlib.sha256(body).hexdigest(),subtitle_bytes=len(body))
        records=[dict(projectId=148,assetId=2,gateType='DOCUMENT',name=FILM+' | EP01 | pt-BR | synthetic',url=row['subtitle_url'])]
        client=MagicMock();response=client.http.get.return_value.__enter__.return_value
        response.status_code=200;response.iter_content.return_value=[body]
        verify_subtitle(client,row,records)
        response.iter_content.return_value=[b'changed']
        with self.assertRaisesRegex(ValueError,'content differs'):verify_subtitle(client,row,records)
        records[0]['name']=FILM+' | EP02 | pt-BR | wrong'
        with self.assertRaisesRegex(ValueError,'identity'):verify_subtitle(client,row,records)


if __name__=='__main__':unittest.main()
