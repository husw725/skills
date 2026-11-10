import unittest

from analytics_v2 import PageDataError
from episode_details import normalize, validate_record


class EpisodeTests(unittest.TestCase):
    def test_gaps_and_highlights_stay_distinct_and_item_ids_are_excluded(self):
        data = dict(start_date='2026-03-01', end_date='2026-11-10', episodes=[
            dict(episode_num='1', innerfeed_vv='281', is_highlight='0', item_id='private', item_ids=['private']),
            dict(episode_num='3', innerfeed_vv='0', is_highlight='0'),
            dict(episode_num='1', innerfeed_vv='10', is_highlight='1')])
        value = normalize(data)
        self.assertEqual([r['episode'] for r in value['rows'] if not r['highlight']], [1, 3])
        self.assertEqual(value['rows'][1]['qv'], 0)
        self.assertNotIn('item_id', value['rows'][0])
        record = dict(value, schema=2, id='123', source='contract_episode_snapshot',
            queryMode='cumulative_snapshot', dataThrough=None, asOf='2026-11-08',
            lastAttempt='2026-11-10T06:00:00+00:00', checked='2026-11-10T06:00:01+00:00')
        # A platform range ending today is not promoted to a verified watermark.
        validate_record(record, '123')
        self.assertIsNone(record['dataThrough'])
        with self.assertRaises(PageDataError):
            validate_record(dict(record, dataThrough='2026-11-10'), '123')

    def test_duplicate_episodes_fractional_counts_and_empty_responses_are_rejected(self):
        row = dict(episode_num='1', innerfeed_vv='2', is_highlight='0')
        for rows in ([row, row], [dict(row, innerfeed_vv='2.5')], [], [dict(row, episode_num='99999999')]):
            with self.assertRaises(PageDataError):
                normalize(dict(start_date='2026-03-01', end_date='2026-11-10', episodes=rows))


if __name__ == '__main__':
    unittest.main()
