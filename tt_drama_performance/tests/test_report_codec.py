import copy
import json
import unittest

from report_codec import encode_payload, pack_payload, read_report_payload, unpack_payload


class ReportCodecTests(unittest.TestCase):
    def test_lossless_roundtrip_including_missing_zero_and_special_names(self):
        value = {'schema': 2, 'emptyObject': {}, 'emptyList': [], 'values': [None, False, True, 0, -1, -2, 1.25],
                 'rows': [{'id': '1234567890123456789', 'name': '中文 </script> & text', 'date': '2026-11-08'},
                          {'id': '1234567890123456789', 'name': '中文 </script> & text', 'date': '2026-11-08'}],
                 '__proto__': {'polluted': 'never'}, 'constructor': 'preserved'}
        before = copy.deepcopy(value)
        encoded = encode_payload(value)
        self.assertNotIn('</script>', encoded)
        self.assertEqual(unpack_payload(json.loads(encoded)), value)
        self.assertEqual(value, before)

    def test_plain_and_compact_reports_are_both_readable(self):
        value = {'schema': 2, 'rows': [{'id': 'same-title', 'qv': 0}]*10}
        self.assertEqual(read_report_payload('const DATA = '+json.dumps(value)+';\n'), value)
        self.assertEqual(read_report_payload('const DATA = decodeReportData('+encode_payload(value)+');\n'), value)
        self.assertEqual(unpack_payload(value), value)

    def test_repeated_rows_are_smaller_and_nonfinite_data_is_rejected(self):
        value = {'rows': [{'id': '1234567890123456789', 'source': 'page_v2', 'qv': i, 'date': '2026-11-08'} for i in range(100)]}
        self.assertLess(len(encode_payload(value)), len(json.dumps(value)) * .65)
        self.assertEqual(unpack_payload(pack_payload(value)), value)
        with self.assertRaises(ValueError):
            encode_payload({'qv': float('nan')})

    def test_invalid_references_are_rejected_instead_of_returning_wrong_data(self):
        for node in ([], [True], [-3], [-2, -1], [-2, 0, 1], [1]):
            with self.subTest(node=node), self.assertRaises(ValueError):
                unpack_payload(dict(_reportEncoding='compact-v1', shapes=[[]], strings=['x'], root=node))


if __name__ == '__main__':
    unittest.main()
