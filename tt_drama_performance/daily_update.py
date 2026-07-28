#!/usr/bin/env python3
"""TikTok Drama Center 日报一体化更新程序（跨平台，Windows 定时任务友好）。

用法:
  python daily_update.py --login    # 首次运行：打开浏览器，人工登录一次（登录态存 browser_profile/）
  python daily_update.py            # 日常：导出 xlsx + 抓趋势 + 重新生成 report.html
  python daily_update.py --push     # 同上，并把 data/ 和 report.html 推送到 git
  python daily_update.py --headless # 无窗口运行（登录态已保存时可用）

退出码: 0 成功 / 2 登录态失效（需重跑 --login）/ 3 导出失败 / 4 其他错误
依赖: pip install playwright openpyxl && playwright install chromium
"""
import argparse, datetime, json, os, subprocess, sys

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
PROFILE = os.path.join(BASE, 'browser_profile')
URL = 'https://www.tiktokdramacenter.com/analytics/content-performance'

CFG = {'dingtalk_webhook': '', 'git_push': True, 'headless': False}
try:
    CFG.update(json.load(open(os.path.join(BASE, 'config.json'), encoding='utf-8')))
except FileNotFoundError:
    pass

# 从 React fiber 状态提取机构级每日指标（与 scripts/extract_daily.js 同源）
EXTRACT_JS = """
() => {
  const rootEl = [...document.querySelectorAll('*')].find(el => Object.keys(el).some(k => k.startsWith('__reactContainer$')));
  if (!rootEl) return null;
  const rootKey = Object.keys(rootEl).find(k => k.startsWith('__reactContainer$'));
  let queue = [rootEl[rootKey]], seen = new Set(), daily = null, n = 0;
  const isDaily = a => Array.isArray(a) && a.length && a[0] && a[0].eventDate && a[0].metrics && !a[0].collectionID;
  while (queue.length && n < 50000) {
    const f = queue.shift(); n++;
    if (!f || seen.has(f)) continue; seen.add(f);
    try {
      for (const c of [f.memoizedProps, f.memoizedState]) {
        if (!c || typeof c !== 'object') continue;
        const vals = [c, ...Object.values(c).filter(v => v && typeof v === 'object')];
        for (const v of vals) {
          if (isDaily(v) && (!daily || v.length > daily.length)) daily = v;
          if (typeof v === 'object') for (const vv of Object.values(v))
            if (isDaily(vv) && (!daily || vv.length > daily.length)) daily = vv;
        }
      }
    } catch (e) {}
    if (f.child) queue.push(f.child);
    if (f.sibling) queue.push(f.sibling);
  }
  return daily;
}
"""


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def notify(text):
    """钉钉通知。webhook 配在 config.json（仓库公开，该文件不入库）；未配置则跳过。"""
    wh = CFG.get('dingtalk_webhook', '').strip()
    if not wh.startswith('https://'):
        return
    try:
        import urllib.request
        payload = json.dumps({'msgtype': 'text', 'text': {'content': text}}).encode('utf-8')
        req = urllib.request.Request(wh, data=payload,
                                     headers={'Content-Type': 'application/json; charset=utf-8'})
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if r.get('errcode') != 0:
            log(f'钉钉通知被拒: {r.get("errmsg")}')
    except Exception as e:
        log(f'钉钉通知失败: {e}')


def open_page(p, headless):
    kw = dict(headless=headless,
              args=['--disable-blink-features=AutomationControlled'],
              viewport={'width': 1440, 'height': 900}, locale='en-US',
              accept_downloads=True)
    ch = CFG.get('browser_channel', 'chrome')
    try:
        # channel='chrome' 用系统已装的 Google Chrome，无需 playwright install chromium
        ctx = p.chromium.launch_persistent_context(PROFILE, channel=ch, **kw) if ch \
            else p.chromium.launch_persistent_context(PROFILE, **kw)
    except Exception as e:
        log(f'系统 Chrome 启动失败（{e.__class__.__name__}），回退到 Playwright 自带 Chromium…')
        ctx = p.chromium.launch_persistent_context(PROFILE, **kw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(URL, wait_until='domcontentloaded', timeout=60000)
    return ctx, page


def logged_in(page, timeout=20000):
    try:
        page.get_by_text('Export Data').first.wait_for(state='visible', timeout=timeout)
        return True
    except PWTimeout:
        return False


def do_login(p):
    ctx, page = open_page(p, headless=False)
    log('正在检测登录状态…')
    if logged_in(page, timeout=15000):
        log('当前已是登录状态，无需操作。')
        ctx.close()
        return 0
    log('未登录：请在打开的浏览器窗口中完成登录（最多等 5 分钟）…')
    if logged_in(page, timeout=300000):
        log('登录成功，登录态已保存到 browser_profile/，以后无需再登录。')
        ctx.close()
        return 0
    log('5 分钟内未检测到登录成功。')
    ctx.close()
    return 2


def run(push, headless):
    today = datetime.date.today().isoformat()
    os.makedirs(DATA, exist_ok=True)
    with sync_playwright() as p:
        ctx, page = open_page(p, headless)
        try:
            if not logged_in(page):
                log('登录态失效：请先运行  python daily_update.py --login')
                notify('【TikTok短剧日报】登录态失效，今日数据未更新。'
                       '请到 Windows 机器上双击 login.bat 重新登录一次即可恢复。')
                return 2

            # 1) 导出 xlsx（直接接住下载，不经过下载目录）
            xlsx = os.path.join(DATA, f'content_performance_{today}.xlsx')
            try:
                with page.expect_download(timeout=30000) as dl:
                    page.get_by_text('Export Data').first.click()
                dl.value.save_as(xlsx)
            except PWTimeout:
                log('导出失败：点击 Export Data 后 30 秒内没有产生下载。')
                notify('【TikTok短剧日报】导出失败（页面可能改版），今日数据未更新，请人工检查。')
                return 3
            if os.path.getsize(xlsx) < 1000:
                log(f'导出文件异常（{os.path.getsize(xlsx)} bytes），中止。')
                return 3
            log(f'快照已保存 {os.path.basename(xlsx)} ({os.path.getsize(xlsx)} bytes)')

            # 2) 抓每日趋势（React 状态，一次拿全量，无需分块）
            daily = page.evaluate(EXTRACT_JS)
            if not daily:
                log('警告：未能从页面状态提取每日趋势（页面结构可能变了），跳过该数据源。')
            else:
                jf = os.path.join(DATA, f'daily_stats_{today}.json')
                json.dump({'daily': daily}, open(jf, 'w'), ensure_ascii=False, indent=1)
                log(f'趋势数据 {len(daily)} 天 -> {os.path.basename(jf)}'
                    f'（{daily[0]["eventDate"]} ~ {daily[-1]["eventDate"]}）')
        finally:
            ctx.close()

    # 3) 重新生成报告
    r = subprocess.run([sys.executable, os.path.join(BASE, 'generate_report.py')],
                       capture_output=True, text=True)
    print(r.stdout, r.stderr)
    if r.returncode != 0:
        return 4
    # 数据校验：报告必须包含今天的快照日期
    if today not in open(os.path.join(BASE, 'report.html'), encoding='utf-8').read():
        log('警告：report.html 中未找到今天的快照日期。')

    # 4) 可选推送
    if push:
        for cmd in (['git', 'add', 'data', 'report.html'],
                    ['git', 'commit', '-m', f'data: daily update {today}'],
                    ['git', 'push']):
            r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
            if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
                log(f'git 失败: {" ".join(cmd)}\n{r.stderr.strip()}')
                return 4
        log('已推送到远端。')
    log('完成。')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--login', action='store_true', help='首次人工登录')
    ap.add_argument('--push', action='store_true', help='更新后 git 推送')
    ap.add_argument('--headless', action='store_true', help='无浏览器窗口运行')
    a = ap.parse_args()
    if a.login:
        with sync_playwright() as p:
            sys.exit(do_login(p))
    sys.exit(run(a.push or CFG['git_push'], a.headless or CFG['headless']))
