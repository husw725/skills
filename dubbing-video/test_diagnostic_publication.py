import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import publish_diagnostic_review as pub
from translate import save_json
from dub_episode import digest


class PublicationTests(unittest.TestCase):
    def test_idempotent_and_preserves_old_version(self):
        with tempfile.TemporaryDirectory() as temp:
            prior = Path.cwd(); os.chdir(temp)
            try:
                root = Path('output/drama-01/episode-07/diagnostic-v2'); root.mkdir(parents=True)
                video = root/'Carmilla_EP07_pt-BR_diagnostic_v2.mp4'; video.write_bytes(b'verified fixture')
                sha = digest(video)
                save_json(root/'render-report.json', {'episode': 7, 'status': 'rendered_diagnostic_candidate',
                     'video_payload_identical': True, 'new_clone_count': 0, 'new_tts_task_count': 13,
                     'output_sha256': sha, 'duration_seconds': 80})
                folder = Path('output/review-publication/148/Carmilla/diagnostic-ep07-v2'); folder.mkdir(parents=True)
                save_json(folder/'upload.private.json', {'url': 'https://example.test/new.mp4', 'sha256': sha,
                                                         'remote_sha256_verified': True})
                rows = [{'projectId': 148, 'gateType': 'FINAL_CUT', 'name': 'Carmilla | EP.07 | pt-BR',
                         'assetId': 2359, 'version': 1, 'url': 'https://example.test/old.mp4', 'tags': []}]
                class Fake:
                    mutations = 0
                    def __init__(self, config): pass
                    def call(self, name, args):
                        if name == 'getReviewMaterialHistory': return list(rows)
                        self.mutations += 1
                        rows.append({**args['material'], 'assetId': 9999, 'version': 2})
                        return {'assetId': 9999}
                fake = Fake(None)
                with patch.object(pub, 'Mflix', return_value=fake):
                    pub.publish(7, None); pub.publish(7, None)
                self.assertEqual(fake.mutations, 1); self.assertEqual([(r['assetId'], r['version']) for r in rows], [(2359,1),(9999,2)])
                # A different version must stop before a mutation.
                rows[1]['url'] = 'https://example.test/another.mp4'
                with patch.object(pub, 'Mflix', return_value=fake), self.assertRaises(ValueError): pub.publish(7,None)
                self.assertEqual(fake.mutations, 1)
                save_json(folder/'upload.private.json', {'sha256': 'changed'})
                with patch.object(pub, 'Mflix', return_value=fake), self.assertRaises(ValueError): pub.publish(7,None)
                self.assertEqual(fake.mutations, 1)
            finally: os.chdir(prior)

    def test_rejects_other_episodes(self):
        for n in (1,2,8,28,30):
            with self.assertRaises(ValueError): pub.publish(n,None)


if __name__ == '__main__': unittest.main()
