import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from report_codec import encode_payload, read_report_payload, unpack_payload
from report_delivery import build_web_report, verify_asset


class ReportDeliveryTests(unittest.TestCase):
    def test_large_episode_records_are_split_by_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'template.html').write_text('const DATA = decodeReportData(/*__DATA__*/null);', encoding='utf-8')
            payload = dict(schema=2, episodeInsights={'101': {'id': '101', 'values': [0, None]},
                                                      '102': {'id': '102', 'values': [1]}},
                           episodeInsightCatalog=[dict(id='101'), dict(id='102')])
            web, assets = build_web_report(base, payload)
            core = read_report_payload(web.read_text(encoding='utf-8'))
            self.assertEqual(core['episodeInsights'], {})
            self.assertEqual(set(core['_sections']), {'episode-101', 'episode-102'})
            restored = {}
            for _, path in assets:
                record = unpack_payload(json.loads(path.read_bytes()))['data']['episodeInsightRecord']
                restored[record['id']] = record
            self.assertEqual(restored, payload['episodeInsights'])

    def test_sections_reassemble_exactly_and_old_versions_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            template = '<script>const DATA = decodeReportData(/*__DATA__*/null);</script>'
            payload = dict(schema=2, legacyDaily=[{'qv': 0, 'shares': None}],
                           dayDetails={'2026-11-08': [['123', 0, None]]},
                           seriesHistory=[], seriesDetails=[{'id': '123', 'name': '中文'}],
                           episodeDetails={'123': {'rows': [{'episode': 1, 'qv': 0}]}})
            (base / 'template.html').write_text(template, encoding='utf-8')
            offline = template.replace('/*__DATA__*/null', encode_payload(payload))
            (base / 'report.html').write_text(offline, encoding='utf-8')
            web, assets = build_web_report(base)
            core = read_report_payload(web.read_text(encoding='utf-8'))
            manifest = core.pop('_sections')
            for name, spec in manifest.items():
                body = (web.parent / spec['path']).read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), spec['sha256'])
                packet = unpack_payload(json.loads(body))
                self.assertEqual(packet['section'], name)
                core.update(packet['data'])
            self.assertEqual(core, payload)
            self.assertEqual((base / 'report.html').read_text(encoding='utf-8'), offline)
            old = {relative: path.read_bytes() for relative, path in assets}
            broken = assets[0][1]
            broken.write_bytes(b'{}')
            with self.assertRaises(ValueError):
                verify_asset(assets[0][0], broken)
            build_web_report(base, payload)
            self.assertEqual(broken.read_bytes(), old[assets[0][0]])
            verify_asset(assets[0][0], broken)
            payload['episodeDetails']['123']['rows'][0]['qv'] = 1
            _, new_assets = build_web_report(base, payload)
            self.assertNotEqual(assets[0][0], new_assets[0][0])
            self.assertEqual(assets[1:][0][0], new_assets[1:][0][0])
            for relative, body in old.items():
                self.assertEqual((web.parent / relative).read_bytes(), body)

    def test_interrupted_atomic_replacement_leaves_no_partial_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'template.html').write_text('const DATA = decodeReportData(/*__DATA__*/null);', encoding='utf-8')
            payload = dict(episodeDetails={'123': {'qv': 0}})
            _, assets = build_web_report(base, payload)
            relative, path = assets[0]
            original = path.read_bytes()
            path.unlink()
            with patch('report_delivery.os.replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    build_web_report(base, payload)
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob('*.tmp')), [])
            build_web_report(base, payload)
            self.assertEqual(path.read_bytes(), original)
            verify_asset(relative, path)


if __name__ == '__main__':
    unittest.main()
