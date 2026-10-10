import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from publish_dashboard import build_html,collect,publish_subtitle
from dub_episode import digest
from translate import save_json


class DashboardTests(unittest.TestCase):
    def test_subtitles_match_rendered_dialogue_and_reuse_verified_upload(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);state={};client=Mock()
            report={'episode':32,'output_sha256':'video-hash','duration_seconds':20,
                'utterances':[{'id':'a','start':13.1,'end':15.7,'translation':'Você vai virar vampira.'},
                    {'id':'b','start':15.7,'end':16.633,'translation':'E daí?'}]}
            def head(**kwargs):
                p=folder/'subtitles/Carmilla_EP32_pt-BR.srt'
                return {'ContentLength':p.stat().st_size,'Metadata':{'sha256':digest(p),'video-sha256':'video-hash'}}
            client.head_object.side_effect=head
            self.assertFalse(publish_subtitle(report,folder,{},state,client,'bucket','prefix/'))
            videos={'32':{'sha256':'video-hash'}}
            self.assertTrue(publish_subtitle(report,folder,videos,state,client,'bucket','prefix/'))
            text=(folder/'subtitles/Carmilla_EP32_pt-BR.srt').read_text(encoding='utf-8')
            self.assertIn('00:00:13,100 --> 00:00:15,700',text)
            self.assertIn('E daí?',text)
            self.assertIn('attachment',client.upload_file.call_args.kwargs['ExtraArgs']['ContentDisposition'])
            self.assertFalse(publish_subtitle(report,folder,videos,state,client,'bucket','prefix/'))
            self.assertEqual(client.upload_file.call_count,1)
            project=folder/'project'
            save_json(project/'output/drama-01/episode-32/dub-v1/render-report.json',report)
            data=collect(project,{'32':{'key':'video.mp4','sha256':'video-hash'}},'https://example.invalid/',state['subtitles'])
            self.assertIn('subtitle_url',data['episodes'][31])
            state['subtitles']['32']['video_sha256']='old-version'
            self.assertNotIn('subtitle_url',collect(project,{'32':{'key':'video.mp4','sha256':'video-hash'}},'https://example.invalid/',state['subtitles'])['episodes'][31])

    def test_page_bootstrap_does_not_allow_script_injection(self):
        text=build_html('<script type="application/json">__BOOTSTRAP__</script>',{'history':['</script><script>bad</script>']})
        self.assertNotIn('</script><script>bad',text)
        self.assertIn('\\u003c',text)

    def test_playable_count_requires_verified_render_and_upload(self):
        with tempfile.TemporaryDirectory() as root:
            project=Path(root);out=project/'output/drama-01/episode-01/dub-v1'
            save_json(out/'render-report.json',{'episode':1,'status':'rendered_draft','output_sha256':'good','duration_seconds':60})
            data=collect(project,{},'https://example.invalid/')
            self.assertEqual(data['summary']['playable'],0)
            self.assertEqual(len(data['episodes']),32)
            data=collect(project,{'1':{'key':'videos/one.mp4','sha256':'good'}},'https://example.invalid/')
            self.assertEqual(data['summary']['playable'],1)
            self.assertEqual(data['episodes'][0]['video_url'],'https://example.invalid/videos/one.mp4')
            self.assertNotIn('output_sha256',data['episodes'][0])

    def test_queued_files_never_count_as_download_ready(self):
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)
            save_json(project/'output/downloads/download-progress.json',{'episodes':[{'episode':2,'assets':{'video':{'verified':True}}}]})
            self.assertEqual(collect(project,{},'https://example.invalid/')['summary']['assets_ready'],0)

    def test_translation_can_continue_while_production_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            project=Path(root);out=project/'output/drama-01'
            for name in ('source.json','translation.json','screenplay-context.json'):
                save_json(out/'episode-05/editorial'/name,{})
            save_json(out/'queue-progress.json',{'stage':'stopped','public_detail':'第 5 集等待旁白音色选择'})
            save_json(out/'translation-progress.json',{'stage':'translating','episode':9})
            data=collect(project,{},'https://example.invalid/')
            self.assertEqual(data['episodes'][4]['status_label'],'译文已审阅')
            self.assertEqual(data['summary']['editorial_ready'],1)
            self.assertIn('第 5 集',data['summary']['current_detail'])
            self.assertIn('第 9 集',data['summary']['translation_detail'])
            self.assertEqual(data['summary']['production_stage'],'stopped')

    def test_render_start_is_visible_before_first_unit_finishes(self):
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)
            save_json(project/'output/drama-01/queue-progress.json',{'stage':'rendering','episode':1,'detail':'配音启动中'})
            data=collect(project,{},'https://example.invalid/')
            self.assertEqual(data['episodes'][0]['status'],'rendering')
            self.assertEqual(data['summary']['current_detail'],'配音启动中')


if __name__=='__main__':unittest.main()
