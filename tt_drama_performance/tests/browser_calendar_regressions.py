"""Semi's visible shell can precede its date cells and re-render after a click."""
import argparse
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analytics_v2 import PageCapture


def main(channel=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
        page = browser.new_page()
        page.set_content('''<button id="open">Date range</button><div class="semi-datepicker-month-grid-left" style="display:none"></div><button id="confirm">Confirm</button>
        <script>window.clicks=0;window.confirmed=false;
        function render(){const panel=document.querySelector('.semi-datepicker-month-grid-left');
          panel.innerHTML='<div role="gridcell" title="2026-11-08" aria-label="2026-11-08">8</div>';
          panel.firstChild.onclick=()=>{clicks++;panel.innerHTML='';setTimeout(render,350);};}
        document.querySelector('#open').onclick=()=>{document.querySelector('div').style.display='block';setTimeout(render,350);};
        document.querySelector('#confirm').onclick=()=>{confirmed=true;};</script>''')
        capture = PageCapture(page)
        try:
            capture.select_dates('2026-11-08', '2026-11-08', timeout=3000)
            assert page.evaluate('clicks===2&&confirmed')
        finally:
            capture.close(); browser.close()
    print('PASS: visible empty calendar and post-selection re-render wait for real cells')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--channel')
    main(parser.parse_args().channel)
