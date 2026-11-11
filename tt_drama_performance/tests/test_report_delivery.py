import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from report_codec import encode_payload, read_report_payload, unpack_payload
from report_delivery import build_web_report


class ReportDeliveryTests(unittest.TestCase):
    def test_sections_reassemble_exactly_and_old_versions_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            template = '<script>const DATA = decodeReportData(/*__DATA__*/null);</script>'
            payload = dict(schema=2, legacyDaily=[{'qv': 0, 'shares': None}],
                           dayDetails={'2026-11-08': [['123', 0, None]]},
                           seriesHistory=[], seriesDetails=[{'id': '123', 'name': '中文'}],
                           episodeDetails={'123': {'rows': [{'episode': 1, 'qv': 0}]}})
            (base / 'template.html').write_text(template)
            offline = template.replace('/*__DATA__*/null', encode_payload(payload))
            (base / 'report.html').write_text(offline)
            web, assets = build_web_report(base)
            core = read_report_payload(web.read_text())
            manifest = core.pop('_sections')
            for name, spec in manifest.items():
                body = (web.parent / spec['path']).read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), spec['sha256'])
                packet = unpack_payload(json.loads(body))
                self.assertEqual(packet['section'], name)
                core.update(packet['data'])
            self.assertEqual(core, payload)
            self.assertEqual((base / 'report.html').read_text(), offline)
            old = {relative: path.read_bytes() for relative, path in assets}
            payload['episodeDetails']['123']['rows'][0]['qv'] = 1
            _, new_assets = build_web_report(base, payload)
            self.assertNotEqual(assets[0][0], new_assets[0][0])
            self.assertEqual(assets[1:][0][0], new_assets[1:][0][0])
            for relative, body in old.items():
                self.assertEqual((web.parent / relative).read_bytes(), body)


if __name__ == '__main__':
    unittest.main()
