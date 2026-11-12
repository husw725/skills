import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analytics_v2 import PageDataError, atomic_json, read_json
import episode_insights as insights
from episode_insights import normalize_page, normalize_seconds, validate_record, normalize_material_catalog, normalize_material_stats


def fixture_record():
    request = dict(contract_id='101', start_date='2026-11-01', end_date='2026-11-08', after_order_num=0)
    row = dict(episode_num='1', is_highlight='0', item_id='9001', item_ids=['9001', '9002'],
               innerfeed_vv='100', delta_innerfeed_vv='20', like_cnt='8', delta_like_cnt='2',
               comment_cnt='0', delta_comment_cnt='0', favourite_cnt='2', delta_favourite_cnt='0',
               finish_rate='0.13', avg_play_duration='5.61', impression_pv='1000', click_pv='80')
    body = dict(start_date=request['start_date'], end_date=request['end_date'], episodes=[row],
                pagination=dict(total=1, has_more=False, next_after_order_num=None))
    normalized = normalize_page(body, request)
    seconds = normalize_seconds(dict(item_id='9001', retention_rate=[dict(second=0, rate=1), dict(second=1, rate=.5),
                          dict(second=3, rate=.2), dict(second=5, rate=0)],
                          like_rate=[dict(second=0, rate=0), dict(second=1, rate=.25), dict(second=3, rate=.75)]))
    seconds.update(checked='2026-11-12T01:00:00+00:00', episode=1, highlight=False)
    record = dict(schema=2, source='contract_episode_insights', id='101', name='Test',
                  lastAttempt='2026-11-12T01:00:00+00:00', asOf='2026-11-08', pending=False, failures={},
                  metrics=dict(start=normalized['start'], end=normalized['end'], rows=normalized['rows'],
                               total=1, complete=True, checked='2026-11-12T01:00:00+00:00'),
                  seconds={'9001': seconds})
    return request, body, record


class EpisodeInsightsTests(unittest.TestCase):
    def test_empty_second_response_is_a_fast_item_specific_failure_then_recovers(self):
        class Page:
            def on(self, *args): pass
            def remove_listener(self, *args): pass
        class Request:
            post_data_json = dict(contract_id='101', vid='video')
        class Response:
            status = 200
            url = 'https://example.invalid/analytics/contract/episode-second-stats'
            request = Request()
            def json(self): return self.body
        capture = insights.Capture(Page())
        response = Response()
        response.body = dict(code=0, data=dict(item_id='90011', retention_rate=[], like_rate=[]))
        capture.response(response)
        self.assertIn(('101', '90011'), capture.second_errors)
        self.assertEqual(capture.seconds, {})
        response.body['data']['retention_rate'] = [dict(second=0, rate=1)]
        capture.response(response)
        self.assertNotIn(('101', '90011'), capture.second_errors)
        self.assertEqual(capture.seconds[('101', '90011')]['_sequence'], 2)

    def test_material_pagination_rejects_cross_range_merge(self):
        rows = [dict(itemId=str(i), title='Creative', account=dict(name='', handle='', region=''), published=None, durationSeconds=None) for i in (7001, 7002)]
        class Locator:
            @property
            def first(self): return self
            def count(self): return 0
            def click(self, **kwargs): pass
            def filter(self, **kwargs): return self
        class Page:
            keyboard = type('Keyboard', (), {'press': lambda *args: None})()
            def locator(self, *args): return Locator()
            def get_by_text(self, *args, **kwargs): return Locator()
        class Capture:
            material_catalogs = {('101', 1): dict(total=2, size=1, rows=[rows[0]]), ('101', 2): dict(total=2, size=1, rows=[rows[1]])}
            material_stats = {('101', ('7001',)): dict(start='2026-11-01', end='2026-11-08', values={'7001': dict(impressions=70, clicks=0)}),
                              ('101', ('7002',)): dict(start='2026-11-01', end='2026-11-08', values={'7002': dict(impressions=None, clicks=None)})}
            def wait(self, predicate, *args):
                if not predicate(): raise PageDataError('missing')
        capture = Capture()
        value = insights.collect_materials(Page(), capture, '101')
        self.assertEqual(value['total'], 2)
        self.assertEqual(value['rows'][0]['clicks'], 0)
        self.assertIsNone(value['rows'][1]['clicks'])
        capture.material_stats[('101', ('7002',))]['start'] = '2026-11-02'
        with self.assertRaises(PageDataError):
            insights.collect_materials(Page(), capture, '101')

    def test_material_metadata_units_and_real_zero_are_preserved(self):
        catalog = normalize_material_catalog(dict(total=1, page=1, page_size=100, list=[dict(
            item_id='7001', title='Creative', duration=171039, publish_time='1793360580000', account={})]))
        self.assertEqual(catalog['rows'][0]['durationSeconds'], 171.039)
        self.assertEqual(catalog['rows'][0]['published'], '2026-10-30')
        request = dict(start_date='2026-11-01', end_date='2026-11-08', item_ids=['7001'])
        stats = normalize_material_stats(dict(start_date='2026-11-01', end_date='2026-11-08',
            episodes=[dict(item_id='7001', impression_pv='70', click_pv='0')]), request)
        self.assertEqual(stats['values']['7001'], dict(impressions=70, clicks=0))
        with self.assertRaises(PageDataError):
            normalize_material_stats(dict(start_date='2026-11-01', end_date='2026-11-08',
                episodes=[dict(item_id='other')]), request)

    def test_material_archive_rejects_unsafe_date_and_numeric_strings(self):
        _, _, record = fixture_record()
        record['materials'] = dict(complete=True, total=1, checked=record['lastAttempt'], start=None, end=None,
            rows=[dict(itemId='7001', title='Creative', published='2026-10-30', durationSeconds=171,
                       account=dict(name='', handle='', region=''), impressions=70, clicks=0)])
        validate_record(record, '101')
        for change in ('date', 'string'):
            value = copy.deepcopy(record)
            if change == 'date':value['materials']['rows'][0]['published'] = '<img onerror=alert(1)>'
            if change == 'string':value['materials']['rows'][0]['durationSeconds'] = '171'
            with self.subTest(change=change), self.assertRaises((PageDataError, ValueError)):
                validate_record(value, '101')

    def test_whole_collector_paginates_and_isolates_corrupt_title(self):
        _, _, sample = fixture_record()
        sample['metrics']['rows'][0]['itemIds'] = ['9001', '90011']
        class Locator:
            def __init__(self, page, selector): self.page, self.selector = page, selector
            @property
            def first(self): return self
            @property
            def last(self): return self
            def count(self): return int(self.page.drawer) if 'close' in self.selector else 1
            def get_by_role(self, *args, **kwargs): return self
            def wait_for(self, **kwargs): pass
            def click(self, **kwargs):
                if 'close' in self.selector:
                    self.page.drawer = False; return
                if 'Switch' in self.selector: return
                episode = 2 if 'Episode 2' in self.selector else 1
                value = copy.deepcopy(sample['seconds']['9001']); value['itemId'] = '90011' if episode == 1 else '9002'
                value['checked'] = insights.stamp()
                value.pop('episode'); value.pop('highlight')
                self.page.capture.sequence += 1; value['_sequence'] = self.page.capture.sequence
                self.page.capture.seconds[('102', value['itemId'])] = value
                self.page.drawer = True
            def evaluate(self, *args, **kwargs):
                row = copy.deepcopy(sample['metrics']['rows'][0]); row.update(episode=2, itemId='9002', itemIds=['9002'])
                self.page.capture.pages[('102', '2026-10-10', '2026-11-08', 1)] = dict(
                    rows=[row], total=2, more=False, nextCursor=None)
        class Page:
            drawer = False
            def goto(self, *args, **kwargs):
                self.capture.pages[('102', '2026-10-10', '2026-11-08', 0)] = dict(
                    rows=[sample['metrics']['rows'][0]], total=2, more=True, nextCursor=1)
            def locator(self, selector): return Locator(self, selector)
            def get_by_role(self, role, name, **kwargs): return Locator(self, name)
            def get_by_text(self, text, **kwargs): return Locator(self, text)
            def wait_for_timeout(self, *args): pass
        class Capture:
            def __init__(self, page):
                page.capture = self; self.pages, self.seconds, self.bounds = {}, {}, {}
                self.sequence = 0
            def wait(self, predicate, *args, **kwargs):
                if not predicate(): raise PageDataError('missing response')
            def close(self): pass
        class UI:
            def __init__(self, page): pass
            def close(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'data/v2'
            atomic_json(root / 'latest.json', dict(latest='2026-11-08'))
            atomic_json(root / 'series_catalog.json', {'101': dict(name='Broken'), '102': dict(name='Healthy')})
            broken = root / 'episode_insights/101.json'; broken.parent.mkdir(); broken.write_text('{broken', encoding='utf-8')
            with patch.object(insights, 'Capture', Capture), patch.object(insights, 'PageCapture', UI):
                result = insights.collect(Page(), tmp, log=lambda _: None)
            self.assertIn('error', result['101'])
            self.assertEqual(broken.read_text(encoding='utf-8'), '{broken')
            healthy = read_json(root / 'episode_insights/102.json')
            validate_record(healthy, '102')
            self.assertEqual(healthy['metrics']['total'], 2)
            self.assertEqual(len(healthy['seconds']), 2)
            self.assertIn('90011', healthy['seconds'])
            self.assertFalse(healthy['pending'])

    def test_separate_cumulative_delta_video_scope_and_missing_second(self):
        request, body, record = fixture_record()
        row = normalize_page(body, request)['rows'][0]
        self.assertEqual(row['cumulative']['qv'], 100)
        self.assertEqual(row['added']['qv'], 20)
        self.assertEqual(row['versionCount'], 2)
        self.assertEqual(row['durationSeconds'], 5.61)
        value = record['seconds']['9001']
        self.assertNotIn(2, dict(value['retention']))
        self.assertEqual(dict(value['retention'])[5], 0)
        self.assertIsNone(value['dataThrough'])
        self.assertNotIn('start', value)
        validate_record(record, '101')

    def test_missing_metrics_are_not_zero_and_units_are_preserved(self):
        request, body, _ = fixture_record()
        body['episodes'][0].update(finish_rate=None, avg_play_duration=None, delta_innerfeed_vv=None)
        row = normalize_page(body, request)['rows'][0]
        self.assertIsNone(row['finishRate'])
        self.assertIsNone(row['durationSeconds'])
        self.assertIsNone(row['added']['qv'])
        self.assertEqual(row['added']['com'], 0)

    def test_bad_scope_duplicate_rows_pagination_or_item_identity_rejected(self):
        request, body, _ = fixture_record()
        variants = []
        value = copy.deepcopy(body); value['start_date'] = '2026-10-01'; variants.append(value)
        value = copy.deepcopy(body); value['episodes'] *= 2; variants.append(value)
        value = copy.deepcopy(body); value['pagination'].update(has_more=True, next_after_order_num=0); variants.append(value)
        value = copy.deepcopy(body); value['episodes'][0]['item_ids'] = ['9002']; variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(PageDataError):
                normalize_page(value, request)

    def test_bad_curve_rates_duplicate_seconds_and_empty_payload_rejected(self):
        for points in ([dict(second=1, rate=1.1)], [dict(second=True, rate=.2)],
                       [dict(second=0, rate=.2)]*2, [dict(second=0, rate=float('nan'))], []):
            with self.subTest(points=points), self.assertRaises(PageDataError):
                normalize_seconds(dict(item_id='9001', retention_rate=points, like_rate=[]))

    def test_partial_archive_or_wrong_video_scope_is_rejected(self):
        _, _, record = fixture_record()
        for change in ('partial', 'video', 'timestamp'):
            value = copy.deepcopy(record)
            if change == 'partial': value['metrics']['total'] = 2
            if change == 'video': value['seconds']['9001']['itemId'] = '9002'
            if change == 'timestamp': value['seconds']['9001']['checked'] = '2026-11-12T00:00:00'
            with self.subTest(change=change), self.assertRaises(PageDataError):
                validate_record(value, '101')

    def test_archive_strings_or_null_curve_points_do_not_become_fake_zero(self):
        _, _, record = fixture_record()
        for change in ('duration', 'rate', 'second', 'null-point'):
            value = copy.deepcopy(record)
            if change == 'duration': value['metrics']['rows'][0]['durationSeconds'] = '5.61'
            if change == 'rate': value['metrics']['rows'][0]['finishRate'] = '.1'
            if change == 'second': value['seconds']['9001']['retention'][0][0] = '0'
            if change == 'null-point': value['seconds']['9001']['retention'][0][1] = None
            with self.subTest(change=change), self.assertRaises(PageDataError):
                validate_record(value, '101')

    def test_null_metric_stub_and_independently_missing_like_curve(self):
        _, _, record = fixture_record()
        record['metrics'] = None
        validate_record(record, '101')
        value = normalize_seconds(dict(item_id='9001', retention_rate=[dict(second=0, rate=1)], like_rate=None))
        self.assertEqual(value['likes'], [])


if __name__ == '__main__':
    unittest.main()
