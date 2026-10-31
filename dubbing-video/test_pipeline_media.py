import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import pipeline_media as media
from translate import save_json


class MediaReuseTests(unittest.TestCase):
    def test_verified_existing_stems_need_no_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            import os
            original=os.getcwd()
            try:
                os.chdir(directory)
                root=Path('output/review-project-96/episode-01/pipeline-media-20261031');root.mkdir(parents=True)
                video=Path('original.mp4');video.write_bytes(b'original')
                stem=root/'background.wav';stem.write_bytes(b'candidate stem')
                binding=dict(project_id=96,episode=1,video=str(video),video_sha256=media.digest(video))
                data=dict(source=binding,output_sha256={str(stem):media.digest(stem)})
                save_json(root/'media.private.json',data)
                with patch.object(media,'source_media',return_value=(video,media.digest(video),{})),patch.object(media.subprocess,'run') as runner:
                    self.assertEqual(media.prepare(96,1,Path('ffmpeg'),'cpu'),data)
                    runner.assert_not_called()
                    stem.write_bytes(b'corrupt')
                    with self.assertRaises(ValueError):media.prepare(96,1,Path('ffmpeg'),'cpu')
                    runner.assert_not_called()
            finally:os.chdir(original)


if __name__=='__main__':unittest.main()
