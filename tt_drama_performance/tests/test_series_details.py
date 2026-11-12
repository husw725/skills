import unittest

from analytics_v2 import PageDataError
from series_details import normalize, validate_record, available_observation


class DetailTests(unittest.TestCase):
    def payload(self, **values):
        return dict(start_date='2026-11-02', end_date='2026-11-08', **values)

    def parse(self, endpoint, **values):
        return normalize(endpoint, self.payload(**values), '2026-11-02', '2026-11-08')

    def test_gender_survives_when_platform_withholds_age(self):
        result = self.parse('audience-stats', audience=[dict(male_pct='33.8121',
            female_pct='26.2208', gender_unknown_pct='39.9672')])
        self.assertIsNone(result['age'])
        self.assertEqual(result['gender']['gender_unknown'], 39.9672)

    def test_age_unknown_matches_platform_other_plus_unknown(self):
        result = self.parse('audience-stats', audience=[dict(male_pct='44.5981', female_pct='17.9301',
            gender_unknown_pct='37.4719', l3_pct='5.6212', l4_pct='27.7859', l5_pct='41.4853',
            other_pct='0.6399', age_unknown_pct='24.4677')])
        self.assertAlmostEqual(result['age']['unknown'], 25.1076)

    def test_channel_scopes_stay_separate(self):
        result = self.parse('traffic-stats', channels=[dict(channel_key='fyp', share_pct='100'),
            dict(channel_key='search', share_pct='100', collection_id='123')])
        self.assertIsNone(result[0]['collectionId'])
        self.assertEqual(result[1]['collectionId'], '123')
        with self.assertRaises(PageDataError):
            self.parse('traffic-stats', channels=[dict(channel_key='fyp', share_pct='80')])

    def test_signed_urls_and_unverified_account_percentages_are_not_persisted(self):
        rows = self.parse('accounts', accounts=[dict(collection_id='123', name='Demo', region='BR',
            unique_id='demo', avatar_url='https://example.invalid?signature=secret', uid='999')])
        self.assertEqual(set(rows[0]), {'collectionId', 'name', 'region', 'handle'})
        rows = self.parse('traffic-added', accounts=[dict(collection_id='123', delta_innerfeed_vv='0', share_pct='98')])
        self.assertEqual(rows[0]['qv'], 0)
        self.assertIsNone(rows[0]['like'])
        self.assertNotIn('share_pct', rows[0])

    def test_account_duration_uses_its_own_day_and_seconds_without_percentage_cap(self):
        rows = self.parse('accounts', accounts=[dict(collection_id='123', avg_play_duration='554.00', avg_play_date='2026-11-08')])
        self.assertEqual(rows[0]['averageDurationSeconds'], 554)
        self.assertEqual(rows[0]['averageDurationDate'], '2026-11-08')
        absent = self.parse('accounts', accounts=[dict(collection_id='123', avg_play_duration='554.00')])
        self.assertNotIn('averageDurationSeconds', absent[0])

    def test_wrong_range_duplicate_id_and_invalid_percentage_are_rejected(self):
        with self.assertRaises(PageDataError):
            normalize('accounts', self.payload(accounts=[]), '2026-11-01', '2026-11-08')
        with self.assertRaises(PageDataError):
            self.parse('accounts', accounts=[dict(collection_id='123')]*2)
        with self.assertRaises(PageDataError):
            self.parse('audience-stats', audience=[dict(male_pct='NaN', female_pct='0', gender_unknown_pct='0')])

    def test_corrupt_archive_is_not_used(self):
        with self.assertRaises(PageDataError):
            validate_record(dict(schema=2, source='contract_detail', id='456', name='Wrong title'), '123')
        with self.assertRaises(PageDataError):
            validate_record(dict(schema=2, source='contract_detail', id='123', name='Demo',
                asOf='2026-11-08', lastAttempt='2026-11-10T00:00:00+00:00',
                sections={'accounts': dict(start='2026-11-02', end='2026-11-08',
                    checked='2026-11-10T00:00:00+00:00', data=[dict(collectionId='123', name='Demo',
                        handle='demo', region='BR', avatar_url='signed-secret')])}), '123')

    def test_all_null_distribution_is_rejected_instead_of_counted_as_usable(self):
        for gender, age in [({'male': None, 'female': None, 'gender_unknown': None}, None),
                            (None, {'l3': None, 'l4': None, 'l5': None, 'unknown': None})]:
            with self.subTest(gender=gender, age=age), self.assertRaises(PageDataError):
                validate_record(dict(schema=2, source='contract_detail', id='123', name='Demo',
                    asOf='2026-11-08', lastAttempt='2026-11-10T00:00:00+00:00',
                    sections={'audience-stats': dict(start='2026-11-02', end='2026-11-08',
                        checked='2026-11-10T00:00:00+00:00', data=dict(gender=gender, age=age))}), '123')

    def test_account_source_difference_is_flagged_without_replacing_primary(self):
        from report_v2 import account_comparison
        detail = dict(id='123', sections={'traffic-added': dict(start='2026-11-02', end='2026-11-08',
            data=[dict(qv=120, like=8, fav=3, com=1)])})
        period = dict(start='2026-11-02', end='2026-11-08',
                      rows=[dict(id='123', qv=100, like=8, fav=3, com=1)])
        result = account_comparison(detail, {'last7': period}, {})
        self.assertEqual(result['status'], 'different')
        self.assertEqual(result['platform']['qv'], 120)
        self.assertEqual(result['primary']['qv'], 100)
        self.assertEqual(period['rows'][0]['qv'], 100)
        self.assertEqual(account_comparison(detail, {}, {})['status'], 'unavailable')

    def test_available_range_cannot_reuse_other_title_old_or_future_observations(self):
        observed = dict(start='2026-10-26', end='2026-11-07', checked='2026-11-10T06:01:00+00:00')
        key = ('123', observed['start'], observed['end'], 'audience-stats')
        attempted = '2026-11-10T06:00:00+00:00'
        self.assertEqual(available_observation({key: observed}, '123', 'audience-stats', attempted, '2026-11-08'), observed)
        for values in ({('456', *key[1:]): observed},
                       {(*key[:-1], 'accounts'): observed},
                       {key: dict(observed, checked='2026-11-09T06:00:00+00:00')},
                       {key: dict(observed, end='2026-11-09')}):
            self.assertIsNone(available_observation(values, '123', 'audience-stats', attempted, '2026-11-08'))


if __name__ == '__main__':
    unittest.main()
