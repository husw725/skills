import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import Error as BrowserError

import analytics_v2 as main
import series_history as history


class Page:
    def __init__(self, fail_navigation=False):
        self.visits, self.fail_navigation = [], fail_navigation

    def reload(self, **kwargs):
        pass

    def goto(self, url, **kwargs):
        self.visits.append(url)
        if '/101/' in url and self.fail_navigation:
            raise BrowserError('net::ERR_EMPTY_RESPONSE')
        if hasattr(self, 'series'):
            did = url.split('/series/')[1].split('/')[0]
            self.series.ranges[did] = dict(has_data=False)

    def get_by_role(self, *args, **kwargs):
        return self

    def click(self, **kwargs):
        pass

    def wait_for(self, **kwargs):
        pass


class Curves:
    def __init__(self, page):
        page.series = self
        self.catalog = {'101': dict(name='Broken'), '102': dict(name='Healthy')}
        self.ranges, self.failures, self.curves = {}, {}, {}
        self.total = 2

    def wait(self, predicate, *args, **kwargs):
        assert predicate()

    def close(self):
        pass


class Capture:
    def __init__(self, page):
        self.daily = {}

    def close(self):
        pass


class RetryRecoveryTests(unittest.TestCase):
    def test_history_isolates_bad_archives_and_navigation_and_keeps_failure_time(self):
        for bad in ('{broken', '[]', None):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'data/v2'
                main.atomic_json(root / 'latest.json', dict(latest='2026-11-08', periods={'last30': 'period.json'}))
                main.atomic_json(root / 'periods/period.json', dict(rows=[dict(id='102')]))
                broken = root / 'series/101.json'
                if bad is not None:
                    broken.parent.mkdir(parents=True)
                    broken.write_text(bad, encoding='utf-8')
                page = Page(fail_navigation=bad is None)
                with patch.object(history, 'SeriesCapture', Curves), patch.object(history, 'PageCapture', Capture):
                    result = history.collect(page, tmp, log=lambda _: None)
                    self.assertIn('101', result['failures'])
                    self.assertTrue(any('/102/' in url for url in page.visits))
                    self.assertTrue((root / 'series/102.json').exists())
                    if bad is not None:
                        self.assertEqual(broken.read_text(encoding='utf-8'), bad)
                    first = result['failureChecks']['101']
                    page.visits.clear()
                    again = history.collect(page, tmp, log=lambda _: None)
                    self.assertEqual(again['failureChecks']['101'], first)
                    self.assertFalse(any('/101/' in url for url in page.visits))
                    history.collect(page, tmp, retry_hours=0, log=lambda _: None)
                    if bad is None:
                        self.assertTrue(any('/101/' in url for url in page.visits))

    def test_previous30_retries_expired_legacy_and_new_watermark_failures(self):
        now = dt.datetime.now(dt.timezone.utc)
        for stamp, watermark, expected in (
            ((now-dt.timedelta(hours=25)).isoformat(), '2026-11-08', True),
            ((now-dt.timedelta(hours=1)).isoformat(), '2026-11-08', False),
            (None, '2026-11-08', True),
            ('invalid', '2026-11-08', True),
            ((now-dt.timedelta(hours=1)).isoformat(), '2026-11-07', True),
        ):
            with self.subTest(stamp=stamp, watermark=watermark), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'data/v2'
                failure = dict(start='2026-09-10', end='2026-10-09', reason='HTTP 500')
                if stamp is not None:
                    failure['checked'] = stamp
                main.atomic_json(root / 'latest.json', dict(latest=watermark, unavailablePeriods={'previous30': failure}))
                calls = []

                class PeriodCapture(Capture):
                    def collect(self, start, end):
                        calls.append((start, end))
                        return dict(daily={}, rows=[], audit=dict(trendQv=0))

                with patch.object(main, 'PageCapture', PeriodCapture), patch.object(main, 'needs_refresh', return_value=False), \
                     patch.object(main, 'period_checks', return_value={}):
                    result = main.collect(Page(), tmp, latest='2026-11-08', history_start='2026-11-08', log=lambda _: None)
                self.assertEqual(('2026-09-10', '2026-10-09') in calls, expected)
                if expected:
                    self.assertIn('previous30', result['periods'])
                    self.assertNotIn('previous30', result['unavailablePeriods'])
                else:
                    self.assertEqual(result['unavailablePeriods']['previous30'], failure)

    def test_previous30_failed_attempt_timestamp_is_not_renewed_while_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            class FailedPeriod(Capture):
                def collect(self, start, end):
                    calls.append((start, end))
                    if end == '2026-10-09':
                        raise main.PageDataError('HTTP 500')
                    return dict(daily={}, rows=[], audit=dict(trendQv=0))

            with patch.object(main, 'PageCapture', FailedPeriod), patch.object(main, 'needs_refresh', return_value=False), \
                 patch.object(main, 'period_checks', return_value={}):
                def collect(retry=24):
                    return main.collect(Page(), tmp, latest='2026-11-08', history_start='2026-11-08', retry_hours=retry, log=lambda _: None)
                first = collect()['unavailablePeriods']['previous30']['checked']
                self.assertEqual(collect()['unavailablePeriods']['previous30']['checked'], first)
                self.assertEqual(sum(end == '2026-10-09' for _, end in calls), 1)
                collect(0)
                self.assertEqual(sum(end == '2026-10-09' for _, end in calls), 2)


if __name__ == '__main__':
    unittest.main()
