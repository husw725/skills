import json
from pathlib import Path
import tempfile
import unittest

from publish_dashboard import build_html,collect
from translate import save_json


class DashboardTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
