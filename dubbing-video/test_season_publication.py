import json
from pathlib import Path
import tempfile
import unittest

from publish_season_candidates import append_version
from translate import read_json
from notify_season_complete import verify_delivery,send_private
from types import SimpleNamespace
import contextlib,io,socket


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

    def delivery(self):
        progress={'all_32_published':True,'requires_review':{},'published':{}};rows=[]
        for n in range(1,33):
            sha=f'{n:064x}';asset=n;sub=100+n;url=f'https://example.test/{n}.mp4'
            progress['published'][str(n)]={'episode':n,'asset_id':asset,'subtitle_asset_id':sub,'video_sha256':sha,
                                          'url':url,'version':2,'prior_versions_retained':True,
                                          'subtitle_url':f'https://example.test/{n}.srt','subtitle_sha256':sha}
            rows.extend([{'projectId':148,'gateType':'FINAL_CUT','name':f'Carmilla | EP.{n:02} | pt-BR',
                          'assetId':asset,'url':url,'version':2,'tags':['Carmilla','pt-BR']},
                         {'projectId':148,'gateType':'DOCUMENT','assetId':sub,
                          'name':f'Carmilla | EP.{n:02} | pt-BR subtitles | {sha[:12]}',
                          'url':f'https://example.test/{n}.srt','documentKind':'DOCUMENT',
                          'tags':['Carmilla','pt-BR'],'note':'SRT SHA256 '+sha}])
        return progress,rows

    def test_completion_requires_all_32_videos_and_subtitles_in_live_review(self):
        p,rows=self.delivery();self.assertEqual(len(verify_delivery(p,rows)),32)
        with self.assertRaises(ValueError):verify_delivery(p,rows[:-1])
        p['published'].pop('32')
        with self.assertRaises(ValueError):verify_delivery(p,rows)

    def test_completion_rejects_wrong_version_or_wrong_episode(self):
        p,rows=self.delivery();rows[0]['version']=1
        with self.assertRaises(ValueError):verify_delivery(p,rows)
        p,rows=self.delivery();rows[0]['name']='Carmilla | EP.02 | pt-BR'
        with self.assertRaises(ValueError):verify_delivery(p,rows)

    def test_completion_rejects_subtitle_url_replacement(self):
        p,rows=self.delivery();rows[1]['url']='https://example.test/wrong.srt'
        with self.assertRaises(ValueError):verify_delivery(p,rows)

    def test_sender_error_is_redacted_and_network_timeout_is_bounded(self):
        old=socket.getdefaulttimeout();capture=io.StringIO()
        def fail(url,message):
            self.assertEqual(socket.getdefaulttimeout(),30)
            print('raw private webhook secret');raise SystemExit(1)
        with contextlib.redirect_stdout(capture):
            with self.assertRaisesRegex(RuntimeError,'outcome uncertain'):
                send_private(SimpleNamespace(send_message=fail),'private','message')
        self.assertNotIn('secret',capture.getvalue());self.assertEqual(socket.getdefaulttimeout(),old)


if __name__=='__main__':unittest.main()
