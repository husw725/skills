"""Exercise whole collector loops: a bad cache must not block a later title."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analytics_v2 import atomic_json
import episode_details
import series_details


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


class Page:
    def __init__(self):
        self.visits = []

    def goto(self, url, **kwargs):
        self.visits.append(url)
        if '/102/' not in url:
            return
        if hasattr(self, 'episodes'):
            self.episodes.values['102'] = dict(checked=stamp(),
                platformRange=dict(start='2026-03-01', end='2026-11-10'),
                rows=[dict(episode=1, highlight=False, qv=10)])
        if hasattr(self, 'details') and url.endswith('/audience'):
            self.series.ranges['102'] = dict(has_data=True, min_date='2026-10-10', max_date='2026-11-08')
            for endpoint, data in {
                'audience-stats': dict(gender=dict(male=0, female=60, gender_unknown=40), age=None),
                'traffic-stats': [dict(collectionId=None, key='fyp', pct=100)],
                'accounts': [dict(collectionId='900', name='Account', handle='account', region='BR')],
                'traffic-added': [dict(collectionId='900', qv=10, like=1, com=0, fav=0)],
            }.items():
                self.details.values[('102', '2026-10-10', '2026-11-08', endpoint)] = dict(
                    start='2026-10-10', end='2026-11-08', checked=stamp(), data=data)

    def get_by_role(self, *args, **kwargs):
        return self

    get_by_text = get_by_role

    def click(self, **kwargs):
        pass

    def wait_for(self, **kwargs):
        pass


class Series:
    def __init__(self, page):
        page.series = self
        self.catalog = {'101': dict(name='Broken'), '102': dict(name='Healthy')}
        self.total, self.ranges, self.failures = 2, {}, {}

    def wait(self, predicate, *args, **kwargs):
        assert predicate()

    def close(self):
        pass


class Details:
    def __init__(self, page):
        page.details = self
        self.values, self.errors = {}, {}

    def close(self):
        pass


class UI:
    def __init__(self, page):
        pass

    def close(self):
        pass


class Episodes(Details):
    def __init__(self, page):
        page.episodes = self
        self.values, self.errors = {}, {}


class CollectionIsolationTests(unittest.TestCase):
    def test_bad_detail_cache_is_preserved_while_next_title_refreshes(self):
        # Include syntax, validation and cooldown-timestamp failures.
        cases = ['{broken', '{}', json.dumps(dict(schema=2, source='contract_detail', id='101',
            name='Broken', asOf='2026-11-08', lastAttempt='2026-11-10T00:00:00', sections={}))]
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as base:
                root = Path(base) / 'data/v2'
                atomic_json(root / 'latest.json', dict(latest='2026-11-08', periods={'last30': 'period.json'}))
                atomic_json(root / 'periods/period.json', dict(rows=[dict(id='102')]))
                bad = root / 'details/101.json'
                bad.parent.mkdir(parents=True)
                bad.write_text(content, encoding='utf-8')
                page, logs = Page(), []
                with patch.object(series_details, 'SeriesCapture', Series), \
                     patch.object(series_details, 'DetailCapture', Details), \
                     patch.object(series_details, 'PageCapture', UI):
                    result = series_details.collect(page, base, log=logs.append)
                self.assertEqual(bad.read_text(encoding='utf-8'), content)
                healthy = json.loads((root / 'details/102.json').read_text(encoding='utf-8'))
                series_details.validate_record(healthy, '102')
                self.assertEqual(len(healthy['sections']), 4)
                self.assertEqual(result['withAudience'], 1)
                self.assertEqual(result['invalidArchives'], 1)
                self.assertIn('101', result['processingErrors'])
                self.assertTrue(any('101' in text for text in logs))

    def test_bad_episode_cache_is_preserved_while_next_title_refreshes(self):
        cases = ['{broken', '{}', json.dumps(dict(schema=2, source='contract_episode_snapshot',
            id='101', name='Broken', queryMode='cumulative_snapshot', dataThrough=None,
            asOf='2026-11-08', lastAttempt='2026-11-10T00:00:00'))]
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as base:
                root = Path(base) / 'data/v2'
                atomic_json(root / 'latest.json', dict(latest='2026-11-08'))
                atomic_json(root / 'series_catalog.json', {'101': dict(name='Broken'), '102': dict(name='Healthy')})
                bad = root / 'episodes/101.json'
                bad.parent.mkdir(parents=True)
                bad.write_text(content, encoding='utf-8')
                page, logs = Page(), []
                with patch.object(episode_details, 'EpisodeCapture', Episodes):
                    episode_details.collect(page, base, log=logs.append)
                self.assertEqual(bad.read_text(encoding='utf-8'), content)
                healthy = json.loads((root / 'episodes/102.json').read_text(encoding='utf-8'))
                episode_details.validate_record(healthy, '102')
                self.assertEqual(healthy['rows'][0]['qv'], 10)
                errors = []
                self.assertEqual(set(episode_details.load_episodes(root, errors)), {'102'})
                self.assertEqual(errors, ['101.json'])
                self.assertTrue(any('101' in text for text in logs))


if __name__ == '__main__':
    unittest.main()
