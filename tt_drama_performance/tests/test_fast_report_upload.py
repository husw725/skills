import gzip
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from report_codec import encode_payload, read_report_payload
from report_delivery import build_web_report

import daily_update as updater


class FastReportUploadTests(unittest.TestCase):
    def test_fast_entry_is_gzip_and_original_entry_remains_raw_html(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as base:
                payload = {'seriesDetails': [], 'episodeDetails': {}, 'legacyDaily': [],
                           'seriesHistory': [], 'dayDetails': {'2026-11-08': [[0, None]]}, 'schema': 2}
                template = '<script>const DATA = decodeReportData(/*__DATA__*/null);</script>'
                (Path(base) / 'template.html').write_text(template, encoding='utf-8')
                original = template.replace('/*__DATA__*/null', encode_payload(payload)).encode('utf-8')
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
                self.assertEqual(len(uploads), 6 if enabled else 1)
                if enabled:
                    self.assertEqual(uploads[-1][1], 'aigc/drama/report/tt_drama/report-fast.html')
                    self.assertEqual(uploads[-1][3]['ContentEncoding'], 'gzip')
                    self.assertEqual(uploads[-1][3]['ContentType'], 'text/html; charset=utf-8')
                    web, assets = build_web_report(base)
                    self.assertEqual(gzip.decompress(uploads[-1][2]), web.read_bytes())
                    self.assertIn('_sections', read_report_payload(web.read_text()))
                    for upload, (relative, path) in zip(uploads[1:-1], assets):
                        self.assertTrue(upload[1].endswith(relative))
                        self.assertEqual(gzip.decompress(upload[2]), path.read_bytes())
                        self.assertIn('immutable', upload[3]['CacheControl'])


if __name__ == '__main__':
    unittest.main()
