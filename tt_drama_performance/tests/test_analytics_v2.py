import copy
import json
from pathlib import Path
import tempfile
import unittest

from analytics_v2 import PageDataError, atomic_json, audit_data, needs_refresh, save_day, validate_range
from report_v2 import build_payload


def sample(start='2026-11-08', end='2026-11-08', value=130):
    from analytics_v2 import date_axis
    days = date_axis(start, end)
    total = value * len(days)
    institution = dict(actualDateRangeStart=start, actualDateRangeEnd=end, latestEventDate='2026-11-08',
                       dailyRows=[dict(eventDate=d, metrics={'innerfeedVv': str(value)}) for d in days],
                       summary=dict(innerfeedVv='2804', innerfeedVvDelta=str(total)))
    block = dict(contractID='7698579160616457222', contractInfo=dict(contractTitle='<Sample>',
                 publishTimeSec='1793318400', episodeNum=39, durationSec=2530),
                 aggregatedMetrics=dict(innerfeedVv='2804', likeCnt='1019', commentCnt='1', favouriteCnt='22',
                                        avgPlayDurationPerUser='9', innerfeedVvDelta=str(total),
                                        likeCntDelta='151', commentCntDelta='1', favouriteCntDelta='0'))
    pages = [dict(total='1', latestEventDate='2026-11-08', contractBlocks=[block])]
    return institution, pages


class AnalyticsTests(unittest.TestCase):
    def test_page_increment_not_lagging_or_cumulative_value(self):
        daily, pages = sample()
        record = validate_range('2026-11-08', '2026-11-08', daily, pages)
        self.assertEqual(record['rows'][0]['qv'], 130)
        self.assertEqual(record['rows'][0]['like'], 151)
        self.assertEqual(record['rows'][0]['cumulative']['qv'], 2804)
        self.assertEqual(record['audit']['deviation'], 0)

    def test_rejects_partial_or_duplicate_pagination(self):
        for duplicate in (False, True):
            daily, pages = sample()
            pages[0]['total'] = '2'
            if duplicate:
                pages[0]['contractBlocks'] *= 2
            with self.assertRaises(PageDataError):
                validate_range('2026-11-08', '2026-11-08', daily, pages)

    def test_missing_metric_is_not_zero(self):
        daily, pages = sample()
        del pages[0]['contractBlocks'][0]['aggregatedMetrics']['likeCntDelta']
        with self.assertRaises(PageDataError):
            validate_range('2026-11-08', '2026-11-08', daily, pages)

    def test_rejects_mismatching_trend_and_increment(self):
        daily, pages = sample()
        pages[0]['contractBlocks'][0]['aggregatedMetrics']['innerfeedVvDelta'] = '129'
        with self.assertRaises(PageDataError):
            validate_range('2026-11-08', '2026-11-08', daily, pages)

    def test_rejects_missing_or_repeated_day(self):
        daily, pages = sample()
        daily['dailyRows'] *= 2
        with self.assertRaises(PageDataError):
            validate_range('2026-11-08', '2026-11-08', daily, pages)

    def test_rejects_page_revision_during_collection(self):
        daily, pages = sample()
        pages[0]['latestEventDate'] = '2026-11-07'
        with self.assertRaises(PageDataError):
            validate_range('2026-11-08', '2026-11-08', daily, pages)

    def test_historical_watermarks_can_differ_when_both_cover_the_day(self):
        daily, pages = sample('2026-07-24', '2026-07-24')
        pages[0]['latestEventDate'] = '2026-11-07'
        record = validate_range('2026-07-24', '2026-07-24', daily, pages)
        self.assertEqual(record['contractAsOf'], '2026-11-07')
        self.assertEqual(record['asOf'], '2026-11-08')
        from analytics_v2 import check_record
        record['contractAsOf'] = '2026-07-23'
        with self.assertRaises(PageDataError):
            check_record(record)

    def test_pages_must_share_their_own_watermark(self):
        daily, pages = sample('2026-07-24', '2026-07-24')
        second = copy.deepcopy(pages[0])
        second['latestEventDate'] = '2026-11-07'
        pages.append(second)
        with self.assertRaises(PageDataError):
            validate_range('2026-07-24', '2026-07-24', daily, pages)

    def test_older_day_is_refreshed_when_institution_revises_it(self):
        old = {'audit': {'status': 'ok', 'trendQv': 100}}
        self.assertTrue(needs_refresh(old, '2026-10-20', '2026-11-08', 3, {'2026-10-20': 101}))
        self.assertFalse(needs_refresh(old, '2026-10-20', '2026-11-08', 3, {'2026-10-20': 100}))

    def test_day_revision_preserves_previous_measurement(self):
        daily, pages = sample()
        old = validate_range('2026-11-08', '2026-11-08', daily, pages)
        new = copy.deepcopy(old)
        new['rows'][0]['like'] += 1
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'days/2026-11-08.json'
            atomic_json(path, old)
            save_day(path, new)
            archived = list((Path(folder) / 'revisions').rglob('*.json'))
            self.assertEqual(len(archived), 1)
            self.assertEqual(json.loads(archived[0].read_text()), old)
            self.assertEqual(json.loads(path.read_text()), new)

    def test_report_preserves_history_and_keeps_unavailable_metrics_null(self):
        from analytics_v2 import shift
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            history = {'2026-11-08': dict(vv=200, qv=129, finish=50, likes=10, comments=1, favs=3, shares=1, playDur=500)}
            atomic_json(base / 'data/daily_history.json', history)
            root = base / 'data/v2'
            manifest = dict(latest='2026-11-08', periods={})
            for n in (7, 30):
                for previous in (False, True):
                    end = shift('2026-11-08', -n) if previous else '2026-11-08'
                    start = shift(end, 1-n)
                    d, p = sample(start, end)
                    record = validate_range(start, end, d, p)
                    name = f'{start}_{end}.json'
                    manifest['periods'][('previous' if previous else 'last')+str(n)] = name
                    atomic_json(root / 'periods' / name, record)
            d, p = sample()
            atomic_json(root / 'days/2026-11-08.json', validate_range('2026-11-08', '2026-11-08', d, p))
            atomic_json(root / 'institution_daily.json', {'2026-11-08': 130})
            atomic_json(root / 'latest.json', manifest)
            payload = build_payload(base)
            self.assertIsNone(payload['daily'][-1]['vv'])
            self.assertIsNone(payload['daily'][-1]['finish'])
            self.assertEqual(payload['daily'][-1]['qv'], 130)
            self.assertEqual(payload['legacyDaily'][0]['vv'], 200)
            self.assertEqual(json.loads((base / 'data/daily_history.json').read_text()), history)
            self.assertEqual(payload['moversSeries'][-1]['rows'][0]['d_qv'], 130)
            self.assertIsNone(payload['moversSeries'][-1]['rows'][0]['qv0'])
            count, problems = audit_data(base)
            self.assertEqual(count, 5)
            self.assertEqual(problems, [])
            # The same stored status must not conceal corruption of the source rows.
            day_path = root / 'days/2026-11-08.json'
            corrupt = json.loads(day_path.read_text())
            corrupt['rows'][0]['qv'] = 129
            atomic_json(day_path, corrupt)
            self.assertTrue(audit_data(base)[1])
            atomic_json(day_path, validate_range('2026-11-08', '2026-11-08', d, p))
            # A grouped series gained a member; prior-period growth is unknown.
            atomic_json(base / 'groups.json', {'Series': ['7698579160616457222', 'other']})
            last7_path = root / 'periods' / manifest['periods']['last7']
            current = json.loads(last7_path.read_text())
            extra = copy.deepcopy(current['rows'][0])
            extra.update(id='other', qv=0, like=0, com=0, fav=0)
            current['rows'].append(extra)
            current['audit']['rows'] = 2
            atomic_json(last7_path, current)
            changed = build_payload(base)['periods'][0]['rows'][0]
            self.assertFalse(changed['comparisonCoverage'])
            self.assertIsNone(changed['change'])


if __name__ == '__main__':
    unittest.main()
