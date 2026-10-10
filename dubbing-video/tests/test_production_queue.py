import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from production_queue import PreparationScheduler,prepare,rendered,supervise_renderer
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

    def test_new_translation_is_prepared_during_active_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pool=Mock();scheduler=PreparationScheduler(pool,root,Path('ffmpeg.exe'),Path('bible.json'))
            scheduler.futures[4]=Mock()
            child=Mock();child.poll.side_effect=[None,None,0];child.returncode=0
            def deliver(_):
                folder=root/'episode-05/editorial';folder.mkdir(parents=True,exist_ok=True)
                for name in ('source.json','translation.json','screenplay-context.json'):(folder/name).write_text('{}')
            with patch('production_queue.subprocess.Popen',return_value=child),patch('production_queue.time.sleep',side_effect=deliver):
                supervise_renderer(['fixture'],Mock(),scheduler,4,root/'queue-progress.json')
            pool.submit.assert_called_once_with(prepare,5,Path('ffmpeg.exe'),Path('bible.json'))
            self.assertIn(5,scheduler.futures)

    def test_preparation_does_not_overwrite_active_renderer_inputs(self):
        from process_lock import process_lock
        import os
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with process_lock(Path('output/drama-01/episode-04/production.lock')),patch('production_queue.subprocess.run') as run:
                    with self.assertRaisesRegex(RuntimeError,'Another worker'):prepare(4,Path('ffmpeg.exe'),Path('bible.json'))
                    run.assert_not_called()
            finally:os.chdir(previous)
