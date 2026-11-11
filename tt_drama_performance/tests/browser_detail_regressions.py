"""Real-browser regressions for null portraits, malformed rows and measured zero.

Run from the project root: python tests/browser_detail_regressions.py
Windows system Chrome: add --channel chrome. Reads existing report data and the
current template, writes only temporary HTML, and never contacts the platform.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright


def main(channel=None):
    base = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(base))
    from report_codec import read_report_payload
    report = (base / 'report.html').read_text(encoding='utf-8')
    payload = read_report_payload(report)
    template = (base / 'template.html').read_text(encoding='utf-8')
    now = '2026-11-10T00:00:00+00:00'
    detail = dict(id='123', name='Regression title', sections={'audience-stats': dict(
        start='2026-11-02', end='2026-11-08', checked=now,
        data=dict(gender=dict(male=None, female=None, gender_unknown=None), age=None))})
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
        page = browser.new_page(viewport=dict(width=1280, height=960))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def render(details, episodes):
            data = copy.deepcopy(payload)
            data.update(seriesDetails=details, episodeDetails=episodes)
            html = template.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
            path = Path(tmp) / 'review.html'
            path.write_text(html, encoding='utf-8')
            page.goto(path.as_uri())
            page.wait_for_function("document.documentElement.dataset.reportReady==='true'")
            page.evaluate("LANG='en'; renderAll()")
            assert not errors, errors

        render([detail], {})
        assert page.locator('#detailGender .detail-bar').count() == 0
        assert '0.0%' not in page.locator('#detailGender').inner_text()
        assert '0/1' in page.locator('#detailSummary').inner_text()

        render([], {'123': dict(id='123', name='Malformed episode snapshot', rows={})})
        assert page.locator('#detailEpisodesPlot svg').count() == 0
        assert page.locator('#detailEpisodesData tr').count() == 0
        # A malformed detail must not interrupt later sections of renderAll().
        if payload.get('seriesHistory'):
            assert page.locator('#seriesArchiveCard').is_visible()

        healthy = copy.deepcopy(detail)
        healthy['sections']['audience-stats']['data']['gender'] = dict(male=0, female=60, gender_unknown=40)
        render([healthy], {'123': dict(id='123', name='Healthy episode snapshot', checked=now, rows=[
            dict(episode=1, highlight=False, qv=10), dict(episode=3, highlight=False, qv=0),
            dict(episode=1, highlight=True, qv=4)])})
        assert page.locator('#detailGender .detail-bar').count() == 3
        assert '0.0%' in page.locator('#detailGender').inner_text()
        assert page.locator('#detailAge .detail-bar').count() == 0
        assert '1/1' in page.locator('#detailSummary').inner_text()
        page.evaluate("""() => {
            const original=lineChart;
            lineChart=(el,labels,series,...rest)=>{
                if(el.id==='detailEpisodesPlot')window.episodeValues=series[0].values;
                return original(el,labels,series,...rest);
            };
            renderAll();
        }""")
        assert page.evaluate('window.episodeValues') == [10, None, 0]
        page.locator('#detailEpisodesData').evaluate("el=>{el.closest('details').open=true}")
        page.wait_for_function("document.querySelectorAll('#detailEpisodesData tr').length===4")
        assert page.locator('#detailEpisodesData tr').count() == 4
        page.set_viewport_size(dict(width=390, height=844))
        page.click('#langBtn')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    print('PASS: 3 browser regressions; null stays missing, invalid rows do not crash, measured zero and gaps preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel')
    main(parser.parse_args().channel)
