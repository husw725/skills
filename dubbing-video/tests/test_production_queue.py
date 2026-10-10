import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from production_queue import prepare, rendered
from dub_episode import digest
from translate import save_json


class ProductionQueueTests(unittest.TestCase):
    def test_preparation_uses_export_and_media_only(self):
        import os
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch('production_queue.subprocess.run') as run:
                    self.assertEqual(prepare(4,Path('ffmpeg.exe'),Path('bible.json')),4)
                    calls=[c.args[0][2] for c in run.call_args_list]
                    self.assertEqual(calls,['export_translation.py','build_episode_plan.py'])
                    self.assertTrue(all(c.kwargs['check'] for c in run.call_args_list))
            finally:os.chdir(previous)

    def test_completed_output_requires_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);video=folder/'video.mp4';video.write_bytes(b'fixture')
            save_json(folder/'dub-v1/render-report.json',{'output':str(video),'status':'rendered_draft',
                      'video_payload_identical':True,'output_sha256':digest(video)})
            self.assertTrue(rendered(folder))
            video.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash differs'):rendered(folder)
