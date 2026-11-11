import gzip
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import daily_update as updater


class FastReportUploadTests(unittest.TestCase):
    def test_fast_entry_is_gzip_and_original_entry_remains_raw_html(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as base:
                original = '<html><body>中文 report data</body></html>'.encode('utf-8')
                (Path(base) / 'report.html').write_bytes(original)
                uploads = []

                class Client:
                    def upload_file(self, path, bucket, key, ExtraArgs):
                        uploads.append((bucket, key, Path(path).read_bytes(), ExtraArgs))

                boto = types.SimpleNamespace(client=lambda *a, **kw: Client())
                config = types.SimpleNamespace(Config=lambda **kwargs: kwargs)
                cfg = dict(s3_report_path='report/tt_drama', s3_fast_report=enabled,
                           s3_ak='test-only', s3_sk='test-only')
                with patch.dict('sys.modules', {'boto3': boto, 'botocore.config': config}), \
                     patch.object(updater, 'BASE', base), patch.object(updater, 'CFG', cfg), \
                     patch.object(updater, 'log'):
                    self.assertTrue(updater.sync_s3('2026-11-11'))
                self.assertEqual(uploads[0][1], 'aigc/drama/report/tt_drama/report.html')
                self.assertEqual(uploads[0][2], original)
                self.assertNotIn('ContentEncoding', uploads[0][3])
                self.assertEqual((Path(base) / 'report.html').read_bytes(), original)
                self.assertEqual(len(uploads), 2 if enabled else 1)
                if enabled:
                    self.assertEqual(uploads[1][1], 'aigc/drama/report/tt_drama/report-fast.html')
                    self.assertEqual(uploads[1][3]['ContentEncoding'], 'gzip')
                    self.assertEqual(uploads[1][3]['ContentType'], 'text/html; charset=utf-8')
                    self.assertEqual(gzip.decompress(uploads[1][2]), original)


if __name__ == '__main__':
    unittest.main()
