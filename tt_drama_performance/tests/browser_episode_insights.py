"""Exercise the episode BI page through real same-origin, per-title requests."""
import argparse
import copy
import functools
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from browser_dynamic_regressions import QuietHandler
from test_episode_insights import fixture_record
from report_codec import read_report_payload
from report_delivery import build_web_report


def main(channel=None):
    base = Path(__file__).resolve().parents[1]
    data = read_report_payload((base / 'report.html').read_text(encoding='utf-8'))
    _, _, first = fixture_record()
    row = copy.deepcopy(first['metrics']['rows'][0])
    row.update(episode=2, itemId='9002', finishRate=None, durationSeconds=None)
    row['cumulative']['qv'] = 0; row['added']['qv'] = 0
    first['metrics']['rows'].append(row); first['metrics']['total'] = 2
    second = copy.deepcopy(first); second['id'] = '102'; second['name'] = 'Test Two'
    data['episodeInsights'] = {'101': first, '102': second}
    data['episodeInsightCatalog'] = [dict(id=k, name=v['name'], rows=2, curves=1, pending=False) for k, v in data['episodeInsights'].items()]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); (root / 'template.html').write_bytes((base / 'template.html').read_bytes())
        web, _ = build_web_report(root, data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(web.parent)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
                page = browser.new_page(viewport=dict(width=1440, height=900))
                page.add_init_script("localStorage.setItem('ttdr_lang','zh')")
                requests, errors = [], []
                page.on('request', lambda r: requests.append(r.url))
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.wait_for_function("document.documentElement.dataset.reportReady==='true'")
                assert page.evaluate('Object.keys(DATA.episodeInsights).length') == 0
                assert not [u for u in requests if '/data/episode-' in u]
                page.locator('#episodeOpsCard').scroll_into_view_if_needed()
                page.wait_for_function("document.querySelector('#episodeOpsKpis').textContent.includes('20.0%')")
                assert page.locator('#episodeOpsKpis').inner_text().count('—') == 1
                assert '0.0%' in page.locator('#episodeOpsKpis').inner_text()
                cells = page.locator('#episodeOpsTable tbody tr').nth(1).locator('td').all_text_contents()
                assert cells[1:5] == ['0', '0', '—', '—'], cells
                assert '总点赞数' in page.locator('#episodeOpsCurveNote').inner_text()
                assert '个百分点' in page.locator('#episodeOpsDrops').inner_text()
                assert page.locator('#episodeOpsRetention svg').count() == 1
                page.select_option('#episodeOpsTitleSelect', '102')
                page.wait_for_function("reportLoaded.has('episode-102')&&document.querySelector('#episodeOpsTitleSelect').value==='102'")
                page.select_option('#episodeOpsTitleSelect', '101')
                page.click('#langBtn')
                assert len([u for u in requests if '/data/episode-' in u]) == 2
                assert page.evaluate('DATA.episodeInsights') == data['episodeInsights']
                page.set_viewport_size(dict(width=390, height=844)); page.wait_for_timeout(200)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown(); server.server_close()
    print('PASS: per-title lazy loading; units/scopes; real zero vs missing; second gaps; cached switching; mobile')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--channel')
    main(parser.parse_args().channel)
