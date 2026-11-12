import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import analytics_v2
import daily_update as updater
import episode_insights
from analytics_v2 import atomic_json
from report_codec import encode_payload, read_report_payload
from report_v2 import refresh_episode_report
from test_episode_insights import fixture_record


class IndependentRefreshTests(unittest.TestCase):
    def test_supplemental_refresh_retains_primary_values_and_marks_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            template = 'const DATA = decodeReportData(/*__DATA__*/null);'
            payload = dict(schema=2, dataThrough='2026-11-08', directDays=1, dramas=[], generated='old',
                           kpis={'qv': 7}, daily=[{'date': '2026-11-08', 'qv': 7}], qualityNotes=[], qualityNotes_en=[])
            (base / 'template.html').write_text(template, encoding='utf-8')
            (base / 'report.html').write_text(template.replace('/*__DATA__*/null', encode_payload(payload)), encoding='utf-8')
            _, _, record = fixture_record()
            atomic_json(base / 'data/v2/episode_insights/101.json', record)
            refresh_episode_report(base)
            actual = read_report_payload((base / 'report.html').read_text(encoding='utf-8'))
            for key in ('dataThrough', 'directDays', 'dramas', 'kpis', 'daily'):
                self.assertEqual(actual[key], payload[key])
            self.assertEqual(actual['episodeInsights']['101'], record)
            self.assertIn('主数据刷新未成功', actual['qualityNotes'][-1])
            refresh_episode_report(base)
            repeated = read_report_payload((base / 'report.html').read_text(encoding='utf-8'))
            self.assertEqual(len(repeated['qualityNotes']), 1)
            record['metrics'] = None
            atomic_json(base / 'data/v2/episode_insights/101.json', record)
            stub = refresh_episode_report(base)
            self.assertEqual(stub['episodeInsightCatalog'][0]['rows'], 0)

    def test_main_error_still_collects_independent_source_and_keeps_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            atomic_json(base / 'data/v2/latest.json', dict(latest='2026-11-08'))
            (base / 'report.html').write_text('accepted report', encoding='utf-8')
            (base / 'data/v2/episode_insights').mkdir()
            page, context = MagicMock(), MagicMock()
            page.get_by_role.return_value.count.return_value = 1
            @contextlib.contextmanager
            def browser():
                yield object()
            with patch.object(updater, 'BASE', tmp), patch.object(updater, 'DATA', str(base / 'data')), \
                 patch.object(updater, 'sync_playwright', browser), patch.object(updater, 'open_page', return_value=(context, page)), \
                 patch.object(updater, 'logged_in', return_value=True), patch.object(updater, 'data_date', return_value='2026-11-08'), \
                 patch.object(updater, 'alert_clear'), patch.object(updater, 'log'), \
                 patch.object(analytics_v2, 'collect', side_effect=analytics_v2.PageDataError('HTTP 500')), \
                 patch.object(episode_insights, 'collect', return_value={}) as collect, \
                 patch('report_v2.refresh_episode_report') as refresh, patch('report_v2.build_report') as primary, \
                 patch.object(updater, 'publish_report', return_value=0) as publish:
                self.assertEqual(updater.run(False, True), 4)
            collect.assert_called_once()
            refresh.assert_called_once_with(tmp)
            primary.assert_not_called()
            self.assertEqual(publish.call_args.kwargs['data_paths'], ['data/v2/episode_insights'])
            self.assertFalse(publish.call_args.kwargs['clear_alerts'])
            context.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
