"""Verify compact data and on-demand tables without contacting the platform."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright


def main(channel=None):
    base = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(base))
    from report_codec import encode_payload, read_report_payload, pack_payload
    data = read_report_payload((base / 'report.html').read_text(encoding='utf-8'))
    template = (base / 'template.html').read_text(encoding='utf-8')
    html = template.replace('/*__DATA__*/null', encode_payload(data))
    plain = template.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False))
    assert len(html.encode()) < len(plain.encode()) * .75
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        path = Path(tmp) / 'report.html'
        path.write_text(html, encoding='utf-8')
        browser = p.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
        page = browser.new_page(viewport=dict(width=1440, height=960))
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(path.as_uri())
        page.wait_for_function("document.documentElement.dataset.reportReady==='true'")
        assert page.evaluate('DATA') == data
        special = {'__proto__': {'polluted': 'never'}, 'constructor': 'preserved',
                   'values': [None, False, 0, -1, -2, {}, [], '中文 </script>']}
        decoded = page.evaluate("""packet=>{
            const value=decodeReportData(packet);
            return {value:JSON.stringify(value),own:Object.prototype.hasOwnProperty.call(value,'__proto__'),polluted:({}).polluted??null};
        }""", pack_payload(special))
        assert json.loads(decoded['value']) == special, decoded
        assert decoded['own'] and decoded['polluted'] is None, decoded
        for selector in ('#legacyTable tr', '.coverage-day', '#t1 tr', '#detailEpisodesData tr', '#seriesArchiveData tr'):
            assert page.locator(selector).count() == 0, selector

        page.locator('#legacyCard summary').click()
        page.wait_for_function("document.querySelectorAll('#legacyTable tr').length>0")
        assert page.locator('#legacyTable tr').count() == len(data['legacyDaily']) + 1
        page.locator('#coverageCard summary').click()
        page.wait_for_function("document.querySelectorAll('.coverage-day').length>0")
        assert page.locator('.coverage-day').count() == len(data['historyCoverage'])
        page.click('#langBtn')
        assert page.locator('#legacyTable th').first.inner_text() in ('日期', 'Date')

        # A pending old table callback must not resurrect data after a failed query.
        missing = next((d['date'] for d in data['historyCoverage'] if d['status'] != 'ok'), None)
        page.fill('#historyStart', missing or data['dataThrough'])
        page.fill('#historyEnd', missing or data['historyRequestedStart'])
        page.click('#historyAnalyze')
        page.locator('#t1').evaluate("el=>{el.closest('details').open=true}")
        page.wait_for_timeout(50)
        assert page.locator('#t1 tr').count() == 0
        assert page.locator('#periodTable tr').count() == 0
        page.fill('#historyStart', data['dataThrough'])
        page.fill('#historyEnd', data['dataThrough'])
        page.click('#historyAnalyze')
        assert page.locator('#t1 tr').count() == 2
        assert data['dataThrough'] in page.locator('#t1').inner_text()

        if data.get('seriesHistory'):
            selected = page.locator('#seriesArchiveSelect').input_value()
            archive = next(r for r in data['seriesHistory'] if r['id'] == selected)
            gap = next((d['date'] for d in data['historyCoverage'] if d['date'] not in archive['qv']), None)
            page.fill('#seriesArchiveStart', gap or data['dataThrough'])
            page.fill('#seriesArchiveEnd', gap or data['historyRequestedStart'])
            page.click('#seriesArchiveApply')
            page.locator('#seriesArchiveData').evaluate("el=>{el.closest('details').open=true}")
            page.wait_for_timeout(50)
            assert page.locator('#seriesArchiveData tr').count() == 0
            page.fill('#seriesArchiveStart', archive['start'])
            page.fill('#seriesArchiveEnd', archive['start'])
            page.click('#seriesArchiveApply')
            assert page.locator('#seriesArchiveData tr').count() == 2

        # Open episode data and switch all titles: rows always belong to that title.
        page.locator('#detailEpisodesData').evaluate("el=>{el.closest('details').open=true}")
        for did in page.locator('#detailTitleSelect option').evaluate_all('(es)=>es.map(e=>e.value)'):
            page.select_option('#detailTitleSelect', did)
            rows = data.get('episodeDetails', {}).get(did, {}).get('rows', [])
            assert page.locator('#detailEpisodesData tr').count() == (len(rows) + 1 if rows else 0), did
        assert page.evaluate('DATA') == data
        assert not errors, errors
        browser.close()
    print('PASS: compact DATA identical; closed tables deferred; open/language/date/title updates correct; stale callbacks cleared')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel')
    main(parser.parse_args().channel)
