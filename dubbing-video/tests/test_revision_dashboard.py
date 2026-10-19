import copy,tempfile,io
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch
from cartesia_pilot import bind
from dub_episode import digest
from translate import save_json
from publish_revision_dashboard import delivery,subtitle_link


class RevisionDashboardTests(TestCase):
    def setUp(self):
        p=patch('publish_revision_dashboard.probe',return_value={'format':{'duration':'123.45'}})
        self.probe=p.start();self.addCleanup(p.stop)
        p=patch('publish_revision_dashboard.shutil.which',return_value='ffmpeg.exe')
        p.start();self.addCleanup(p.stop)

    def fixture(self,folder):
        for name in ['reviewed.json','screenplay-context.json']:save_json(folder/name,{'content':name})
        video=folder/'Carmilla_EP05_pt-BR_season-revision.mp4';video.write_bytes(b'rendered-video')
        subtitle=folder/'Carmilla_EP05_pt-BR_revised.srt';subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\nNão.\n',encoding='utf-8')
        plan={'episode':5,'project_id':59,'blocking_issues':[],
              'reviewed_response_sha256':digest(folder/'reviewed.json'),'reviewed_context_sha256':digest(folder/'screenplay-context.json'),
              'translation_srt_sha256':digest(subtitle)}
        save_json(folder/'plan.json',plan);bind(folder/'reviewed-plan-fingerprint.json',plan)
        report={'episode':5,'status':'rendered_season_revision_candidate','video_payload_identical':True,
                'source_audio_in_output':False,'new_clone_count':0,'output_sha256':digest(video)}
        save_json(folder/'render-report.json',report)
        receipt={'episode':5,'asset_id':2690,'subtitle_asset_id':2691,'prior_versions_retained':True,
                 'video_sha256':digest(video),'subtitle_sha256':digest(subtitle),
                 'url':'https://starlitshorts.s3.amazonaws.com/aigc/drama/test/season-revisions/Carmilla_EP05_pt-BR_season-revision-'+digest(video)+'.mp4'}
        return receipt,subtitle

    def test_only_matching_published_version_and_approved_unsigned_origin(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);r,_=self.fixture(folder);base='https://starlitshorts.s3.amazonaws.com/';prefix='aigc/drama/test/'
            self.assertEqual(delivery(5,folder,r,base,prefix,{})[-1],123.45)
            for field,value in [('episode',8),('subtitle_sha256','old'),('video_sha256','old'),('prior_versions_retained',False),
                                ('url','https://other.invalid/aigc/drama/test/videos/ep05.mp4'),
                                ('url',r['url']+'?token=private'),('url','https://starlitshorts.s3.amazonaws.com/aigc/other/videos/ep05.mp4')]:
                with self.assertRaises(ValueError):delivery(5,folder,{**r,field:value},base,prefix,{})

    def test_local_video_tampering_cannot_enter_page(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);r,_=self.fixture(folder);cache={};base='https://starlitshorts.s3.amazonaws.com/'
            delivery(5,folder,r,base,'aigc/drama/test/',cache)
            (folder/'Carmilla_EP05_pt-BR_season-revision.mp4').write_bytes(b'tampered')
            with self.assertRaises(ValueError):delivery(5,folder,r,base,'aigc/drama/test/',cache)

    def test_exact_final_srt_uploaded_once_without_any_video_upload(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);r,sub=self.fixture(folder);s3=Mock();state={}
            s3.head_object.return_value={'ContentLength':sub.stat().st_size,'Metadata':{'sha256':r['subtitle_sha256'],'video-sha256':r['video_sha256']}}
            s3.get_object.side_effect=lambda **kwargs:{'Body':io.BytesIO(sub.read_bytes())}
            args=(5,sub,r,state,s3,'starlitshorts','aigc/drama/test/','https://starlitshorts.s3.amazonaws.com/')
            first=subtitle_link(*args);self.assertEqual(first,subtitle_link(*args));self.assertEqual(s3.upload_file.call_count,1)
            self.assertTrue(s3.upload_file.call_args.args[0].endswith('.srt'))
            self.assertIn('attachment',s3.upload_file.call_args.kwargs['ExtraArgs']['ContentDisposition'])
            state['subtitles']['5']['video_sha256']='another-video'
            subtitle_link(*args);self.assertEqual(s3.upload_file.call_count,2)

    def test_unverified_subtitle_upload_never_enters_cache(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);r,sub=self.fixture(folder);s3=Mock();state={}
            s3.head_object.return_value={'ContentLength':0,'Metadata':{}}
            with self.assertRaises(ValueError):subtitle_link(5,sub,r,state,s3,'starlitshorts','aigc/drama/test/','https://starlitshorts.s3.amazonaws.com/')
            self.assertEqual(state['subtitles'],{})
