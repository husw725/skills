import copy,tempfile,unittest,hashlib
from types import SimpleNamespace
from unittest.mock import patch
from pipeline_publish import upload
from pathlib import Path
from publish_comment_revisions import append,validate_manifest,FILM,PROJECT,freeze,verify_retained_video
from translate import read_json,save_json

class FakeReview:
 def __init__(self):
  self.rows=[dict(projectId=PROJECT,gateType='DOCUMENT',assetId=100,version=1,name=f'{FILM} EP01 V1.srt',url='https://old.example/sub.srt',tags=[],documentKind='DOCUMENT')];self.updates=0;self.unknown=False
 def call(self,name,args):
  if name=='getReviewMaterialHistory':return copy.deepcopy(self.rows)
  if name!='updateReviewMaterialVersion':raise AssertionError(name)
  self.updates+=1;new=dict(args['material'],assetId=101,version=2,parentAssetId=100);self.rows.append(new)
  if self.unknown:raise RuntimeError('Unknown response after accepted write')
  return dict(assetId=101)

class PublishTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
  self.row=dict(episode=1,old_subtitle_asset_id=100,old_subtitle_url='https://old.example/sub.srt',old_subtitle_version=1,subtitle_sha256='b'*64,delivery_note='Synthetic review candidate')
 def test_append_preserves_history_and_is_idempotent(self):
  c=FakeReview();x=append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT');self.assertEqual(x['version'],2);self.assertEqual(c.rows[0]['version'],1);self.assertEqual(c.rows[0]['tags'],[])
  append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT');self.assertEqual(c.updates,1)
 def test_unknown_write_reconciles_existing_version_without_resubmit(self):
  c=FakeReview();c.unknown=True
  with self.assertRaises(RuntimeError):append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT')
  x=append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT');self.assertEqual(x['version'],2);self.assertEqual(c.updates,1)
 def test_document_server_omission_reconciles_without_another_write(self):
  c=FakeReview();c.unknown=True
  with self.assertRaises(RuntimeError):append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT')
  c.rows[-1]['tags']=[]
  x=append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT');self.assertEqual(x['tags'],[]);self.assertEqual(c.updates,1)
  c.rows[-1]['tags']=['unrelated']
  with self.assertRaises(ValueError):append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT')
  self.assertEqual(c.updates,1)
 def test_video_tag_omission_is_rejected_without_repeat_write(self):
  c=FakeReview();c.rows[0].update(gateType='FINAL_CUT',name=f'{FILM} | EP01 | pt-BR | V1')
  row=dict(episode=1,old_video_asset_id=100,old_video_url='https://old.example/sub.srt',old_video_version=1,video_sha256='a'*64,delivery_note='Synthetic',duration=2)
  sub=dict(assetId=200,name=f'{FILM} EP01 V2.srt');c.unknown=True
  with self.assertRaises(RuntimeError):append(c,row,'https://new.example/video.mp4',self.p,'FINAL_CUT',sub)
  c.rows[-1]['tags']=[]
  with self.assertRaises(ValueError):append(c,row,'https://new.example/video.mp4',self.p,'FINAL_CUT',sub)
  self.assertEqual(c.updates,1)
 def test_wrong_episode_history_and_changed_intent_are_rejected(self):
  c=FakeReview();c.rows[0]['name']=f'{FILM} EP02 V1.srt'
  with self.assertRaises(ValueError):append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT')
  self.assertEqual(c.updates,0);c=FakeReview();append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT');ip=self.p/'version-intent.private.json';d=read_json(ip);d['material']['note']='wrong matching subtitle';save_json(ip,d)
  with self.assertRaises(ValueError):append(c,self.row,'https://new.example/sub.srt',self.p,'DOCUMENT')
 def test_frozen_transfer_uses_approved_copy_when_original_changes(self):
  import hashlib,stat
  src=self.p/'source';src.write_bytes(b'approved');h=hashlib.sha256(b'approved').hexdigest();target=self.p/'frozen';freeze(src,target,h);src.write_bytes(b'changed')
  self.assertEqual(target.read_bytes(),b'approved');freeze(src,target,h)
  target.chmod(stat.S_IREAD|stat.S_IWRITE);target.write_bytes(b'bad')
  with self.assertRaises(ValueError):freeze(src,target,h)
 def test_long_windows_delivery_name_uses_short_temporary_basename(self):
  src=self.p/'source';src.write_bytes(b'approved long-path copy');h=hashlib.sha256(src.read_bytes()).hexdigest();target=self.p/('p'*140)/f'{FILM} EP01 V2.srt';freeze(src,target,h);self.assertEqual(target.read_bytes(),src.read_bytes())
 def test_wrong_source_never_becomes_transfer_copy(self):
  src=self.p/'source';src.write_bytes(b'unapproved');target=self.p/'frozen'
  with self.assertRaises(ValueError):freeze(src,target,'a'*64)
  self.assertFalse(target.exists())
 def test_retained_video_uses_trusted_checksum_and_public_access(self):
  src=self.p/'video.mp4';src.write_bytes(b'synthetic video');sha=hashlib.sha256(src.read_bytes()).hexdigest()
  head={'ChecksumSHA256':'synthetic'};s3=SimpleNamespace(head_object=lambda **kw:head);c=SimpleNamespace(http=object())
  with patch('publish_season_candidates.verify_s3_checksum',return_value=True) as check,patch('scoped_s3_transfer.verify_public') as public,patch('publish_comment_revisions.verify_object') as full:
   method=verify_retained_video(c,s3,'https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/retained.mp4',src,sha)
   self.assertIn('authenticated',method);check.assert_called_once_with(src,sha,head);public.assert_called_once();full.assert_not_called()
  with patch('publish_season_candidates.verify_s3_checksum',return_value=False),patch('scoped_s3_transfer.verify_public') as public,patch('publish_comment_revisions.verify_object') as full:
   with self.assertRaises(ValueError):verify_retained_video(c,s3,'https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/retained.mp4',src,sha)
   public.assert_not_called();full.assert_not_called()
 def test_retained_video_without_checksum_or_aws_keeps_full_get(self):
  s3=SimpleNamespace(head_object=lambda **kw:{})
  with patch('publish_comment_revisions.verify_object') as full:
   for aws in [None,s3]:self.assertEqual(verify_retained_video(object(),aws,'https://example/video',self.p/'video','a'*64),'full_public_get_sha256')
   self.assertEqual(full.call_count,2)
 def test_subtitle_download_name_is_sent_and_verified(self):
  src=self.p/f'{FILM} EP01 V2.srt';src.write_bytes(b'synthetic subtitle');h=hashlib.sha256(src.read_bytes()).hexdigest();sent=[]
  def put(url,**kw):sent.append(kw.get('headers'));return SimpleNamespace(status_code=200)
  c=SimpleNamespace(http=SimpleNamespace(put=put));headers={'Content-Type':'application/x-subrip; charset=utf-8','Content-Disposition':f'attachment; filename="{src.name}"'}
  def ledger():return {'uploads':{h:dict(status='upload_pending',sha256=h,bytes=src.stat().st_size,url='https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/new.srt',signed_url='synthetic')}}
  d=ledger()
  with patch('pipeline_publish.verify_object',return_value=headers):upload(c,src,d,self.p/'upload.json',content_headers=headers)
  self.assertEqual(sent[0],headers);self.assertEqual(d['uploads'][h]['status'],'verified')
  d=ledger()
  with patch('pipeline_publish.verify_object',return_value={}):
   with self.assertRaisesRegex(ValueError,'headers differ'):upload(c,src,d,self.p/'bad-upload.json',content_headers=headers)
  self.assertNotEqual(d['uploads'][h]['status'],'verified')
 def manifest(self):
  return dict(film=FILM,target_project=PROJECT,episodes=[dict(episode=i,duration=2.0,reuse_video=True,subtitle_changed=False,video_sha256='a'*64,old_video_sha256='a'*64,subtitle_sha256='b'*64,old_subtitle_sha256='b'*64,old_video_asset_id=1000+i,old_subtitle_asset_id=2000+i,old_video_version=2,old_subtitle_version=1,old_video_url=f'https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/{i}.mp4',old_subtitle_url=f'https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/{i}.srt') for i in range(1,33)])
 def test_complete_package_rejects_missing_duplicate_or_bool_episode(self):
  m=self.manifest();validate_manifest(m)
  for values in [m['episodes'][:-1],[dict(m['episodes'][0],episode=True)]+m['episodes'][1:],[m['episodes'][0]]+m['episodes'][:-1]]:
   with self.assertRaises(ValueError):validate_manifest(dict(m,episodes=values))
 def test_changed_subtitle_requires_exact_clear_next_version_name(self):
  m=self.manifest();r=m['episodes'][0];r.update(reuse_video=False,video_sha256='c'*64,subtitle_changed=True,subtitle_sha256='d'*64,subtitle_path=f'{FILM} EP01 V2.srt');validate_manifest(m)
  r['subtitle_path']='unlabelled.srt'
  with self.assertRaises(ValueError):validate_manifest(m)
 def test_source_url_reuse_flags_and_nonfinite_duration_fail_closed(self):
  for delta in [dict(old_video_url='http://localhost/private'),dict(duration=float('nan')),dict(reuse_video=1),dict(video_sha256='c'*64)]:
   m=self.manifest();m['episodes'][0].update(delta)
   with self.assertRaises(ValueError):validate_manifest(m)

if __name__=='__main__':unittest.main()
