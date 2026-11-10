import unittest

from analytics_v2 import PageDataError
from series_history import parse_curve, upgrade_record


class SeriesHistoryTests(unittest.TestCase):
    def test_missing_dates_remain_missing_instead_of_zero(self):
        data = dict(start_date='2026-03-01', end_date='2026-03-03',
                    points=[dict(event_date='2026-03-01', innerfeed_vv='12'),
                            dict(event_date='2026-03-03', innerfeed_vv='0')])
        result = parse_curve(data, '2026-03-01', '2026-03-03', 'innerfeed_vv')
        self.assertNotIn('2026-03-02', result)
        self.assertEqual(result['2026-03-03'], 0)

    def test_duplicate_day_or_out_of_range_is_rejected(self):
        for points in ([dict(event_date='2026-03-01', innerfeed_vv='2')]*2,
                       [dict(event_date='2026-03-04', innerfeed_vv='2')]):
            with self.assertRaises(PageDataError):
                parse_curve(dict(start_date='2026-03-01',end_date='2026-03-03',points=points),
                            '2026-03-01','2026-03-03','innerfeed_vv')

    def test_empty_curve_stays_empty_and_duration_is_not_fabricated(self):
        data=dict(start_date='2026-03-01',end_date='2026-03-03',points=[])
        self.assertEqual(parse_curve(data,'2026-03-01','2026-03-03','innerfeed_vv'),{})
        data['points']=[dict(event_date='2026-03-01',value=None)]
        self.assertEqual(parse_curve(data,'2026-03-01','2026-03-03','value'),{})

    def test_null_duplicate_and_fractional_counts_are_rejected(self):
        for points in ([dict(event_date='2026-03-01',innerfeed_vv=None),dict(event_date='2026-03-01',innerfeed_vv='2')],
                       [dict(event_date='2026-03-01',innerfeed_vv=1.5)]):
            with self.assertRaises(PageDataError):
                parse_curve(dict(start_date='2026-03-01',end_date='2026-03-03',points=points),
                            '2026-03-01','2026-03-03','innerfeed_vv')

    def test_metadata_upgrade_keeps_old_observation_time_and_partial_status(self):
        old=dict(qv={'2026-03-01':12},dur={},checked='2026-11-10T00:00:00+00:00',
                 segments={'2026-03-01_2026-03-03':dict(status='ok',missing=['2026-03-02'],checked='2026-11-09T00:00:00+00:00')})
        updated=upgrade_record(old)
        self.assertEqual(updated['segments']['2026-03-01_2026-03-03']['status'],'partial')
        self.assertEqual(updated['observedAt']['qv']['2026-03-01'],'2026-11-09T00:00:00+00:00')
        self.assertNotIn('observedAt',old)


if __name__ == '__main__':
    unittest.main()
