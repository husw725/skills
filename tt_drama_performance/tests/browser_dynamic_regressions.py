"""Real HTTP browser checks for deferred data, errors, caching and full fidelity."""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report_codec import read_report_payload
from report_delivery import build_web_report


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main(channel=None):
    base = Path(__file__).resolve().parents[1]
    payload = read_report_payload((base / 'report.html').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'template.html').write_bytes((base / 'template.html').read_bytes())
        web, _ = build_web_report(root, payload)
        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(web.parent)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
                page = browser.new_page(viewport=dict(width=1440, height=900))
                errors, requests = [], []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: requests.append(r.url))
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.wait_for_function("document.documentElement.dataset.reportReady==='true'")
                assert not [u for u in requests if '/data/' in u], requests
                assert page.evaluate('DATA.kpis') == payload['kpis']
                assert page.evaluate('DATA.seriesDetails===undefined')

                # A corrupt HTTP-200 response must be rejected and remain retryable.
                page.route('**/data/details-*.json', lambda route: route.fulfill(status=200, body='{}'))
                page.locator('#seriesDetailsCard').scroll_into_view_if_needed()
                page.wait_for_function("['重试','retry'].some(t=>document.querySelector('#seriesDetailsCard .remote-status').textContent.toLowerCase().includes(t))")
                assert page.evaluate('DATA.seriesDetails===undefined')
                page.unroute('**/data/details-*.json')
                page.locator('#seriesDetailsCard .remote-status button').click()
                page.wait_for_function("reportLoaded.has('details')&&document.querySelector('#detailTitleSelect').options.length>0")
                assert page.evaluate('DATA.episodeDetails') == payload['episodeDetails']
                page.locator('#detailEpisodesData').evaluate("el=>el.closest('details').open=true")
                page.wait_for_function("document.querySelectorAll('#detailEpisodesData tr').length>1")
                page.locator('#langBtn').click()
                page.wait_for_timeout(100)
                assert len([u for u in requests if '/data/details-' in u]) == 2

                page.locator('#seriesArchiveCard').scroll_into_view_if_needed()
                page.wait_for_function("reportLoaded.has('archive')&&document.querySelector('#seriesArchiveSelect').options.length>0")
                page.locator('#legacyCard').evaluate('el=>el.open=true')
                page.wait_for_function("reportLoaded.has('legacy')&&document.querySelectorAll('#legacyTable tr').length>1")
                page.locator('#historyStart').fill(payload['dataThrough'])
                page.locator('#historyEnd').fill(payload['dataThrough'])
                page.locator('#historyAnalyze').click()
                page.wait_for_function("reportLoaded.has('history')&&customPeriod!==null")
                expected = dict(payload)
                actual = page.evaluate('DATA')
                actual.pop('_sections')
                assert actual == expected
                # Concurrent requests after loading must never download again.
                before = len(requests)
                page.evaluate("Promise.all([loadReportSection('history'),loadReportSection('history'),loadReportSection('details')])")
                assert len(requests) == before
                page.set_viewport_size(dict(width=390, height=844))
                page.wait_for_timeout(150)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors, errors
                # A slow custom-date response cannot overwrite a newer preset selection.
                other = browser.new_page(viewport=dict(width=1440, height=900))
                history_requests = []
                other.on('request', lambda r: history_requests.append(r.url) if '/data/history-' in r.url else None)
                other.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                other.wait_for_function("document.documentElement.dataset.reportReady==='true'")
                other.locator('#historyStart').fill(payload['dataThrough'])
                other.locator('#historyEnd').fill(payload['dataThrough'])
                other.route('**/data/history-*.json', lambda route: route.fulfill(status=404, body='missing'))
                other.locator('#historyAnalyze').click()
                other.wait_for_function("document.querySelector('#periodMeta button')!==null")
                assert other.evaluate('DATA.dayDetails===undefined')
                assert other.evaluate('DATA.kpis') == payload['kpis']
                other.unroute('**/data/history-*.json')
                other.evaluate("""()=>{const original=window.fetch;window.fetch=async(...args)=>{
                    if(String(args[0]).includes('/data/history-'))await new Promise(r=>setTimeout(r,600));
                    return original(...args);};}""")
                other.locator('#historyAnalyze').click()
                other.locator('#historyAnalyze').click()
                other.select_option('#periodSelect', '0')
                other.wait_for_function("reportLoaded.has('history')")
                assert other.evaluate('periodSelection===0&&customPeriod===null')
                assert len(history_requests) == 2, history_requests  # failed request + one shared retry
                other.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('PASS: no initial detail downloads; checksum failure/retry; all sections identical; cached; bilingual/mobile')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel')
    main(parser.parse_args().channel)
