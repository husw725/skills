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
import argparse, datetime, json, os, re, subprocess, sys, time

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
    log('未登录：请在打开的浏览器窗口中完成登录（每 5 秒自动检测，最多等 10 分钟）…')
    deadline = time.time() + 600
    while time.time() < deadline:
        if logged_in(page, timeout=4000):
            log('登录成功，登录态已保存到 browser_profile/，以后无需再登录。')
            ctx.close()
            return 0
        u = page.url
        # 登录成功后站点常跳去首页，Export Data 按钮不在那里——拉回数据页再检测。
        # 正在登录页（login/passport）时不要动，避免打断用户输入。
        if 'login' not in u and 'passport' not in u and '/analytics/content-performance' not in u:
            try:
                page.goto(URL, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
        time.sleep(1)
    log('10 分钟内未检测到登录成功。')
    ctx.close()
    return 2


def sync_pages_repo(today):
    """把 report.html 作为 index.html 同步到独立的 GitHub Pages 仓库（config: pages_repo_dir）。
    未配置或目录不存在则跳过；失败不影响主流程。"""
    d = CFG.get('pages_repo_dir', '').strip()
    if not d:
        return
    if not os.path.isabs(d):
        d = os.path.normpath(os.path.join(BASE, d))
    if not os.path.isdir(os.path.join(d, '.git')):
        log(f'pages_repo_dir 不是 git 仓库，跳过分享页同步: {d}')
        return
    import shutil
    shutil.copyfile(os.path.join(BASE, 'report.html'), os.path.join(d, 'index.html'))
    for cmd in (['git', 'add', 'index.html'],
                ['git', 'commit', '-m', f'daily report {today}'],
                ['git', 'push']):
        r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
        if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
            log(f'分享页同步失败: {" ".join(cmd)} -> {r.stderr.strip()[:200]}')
            return
    log('分享页(tt-drama-report)已同步。')


# 从剧目明细表（React 状态）提取合同级元信息：上线时间/集数/版本。表格分页，需配合翻页调用。
META_JS = """
() => {
  const rootEl = [...document.querySelectorAll('*')].find(el => Object.keys(el).some(k => k.startsWith('__reactContainer$')));
  if (!rootEl) return null;
  const rootKey = Object.keys(rootEl).find(k => k.startsWith('__reactContainer$'));
  let queue = [rootEl[rootKey]], seen = new Set(), best = null, n = 0;
  const isRows = a => Array.isArray(a) && a.length && a[0] && a[0].contractInfo;
  while (queue.length && n < 60000) {
    const f = queue.shift(); n++;
    if (!f || seen.has(f)) continue; seen.add(f);
    try {
      for (const c of [f.memoizedProps, f.memoizedState]) {
        if (!c || typeof c !== 'object') continue;
        for (const v of [c, ...Object.values(c).filter(x => x && typeof x === 'object')]) {
          for (const cand of [v, ...(typeof v === 'object' ? Object.values(v) : [])]) {
            if (isRows(cand) && (!best || cand.length > best.length)) best = cand;
          }
        }
      }
    } catch (e) {}
    if (f.child) queue.push(f.child);
    if (f.sibling) queue.push(f.sibling);
  }
  return (best || []).map(r => ({id: r.contractID, title: (r.contractInfo||{}).contractTitle,
    pub: (r.contractInfo||{}).publishTimeSec, eps: (r.contractInfo||{}).episodeNum,
    cols: (r.collections||[]).map(c => c.collectionID)}));
}
"""

NEXT_PAGE_JS = """
(n) => {
  const el = [...document.querySelectorAll('.semi-page-item')].find(e => e.textContent.trim() === String(n));
  if (!el) return false;
  el.click();
  return true;
}
"""


def collect_meta(page):
    """翻遍剧目明细表，合并写 data/drama_meta.json（上线日期用 UTC，与平台显示一致）。失败不影响主流程。"""
    mf = os.path.join(DATA, 'drama_meta.json')
    try:
        meta = json.load(open(mf, encoding='utf-8'))
    except Exception:
        meta = {}
    got = 0
    for pageno in range(2, 12):  # 先抓当前页，再点 2..N
        rows = page.evaluate(META_JS) or []
        for r in rows:
            if not r.get('id') or not r.get('pub'):
                continue
            meta[str(r['id'])] = {
                'title': r['title'], 'pub': int(r['pub']),
                'launch': datetime.datetime.utcfromtimestamp(int(r['pub'])).date().isoformat(),
                'episodes': r['eps'], 'collections': r['cols']}
            got += 1
        if not page.evaluate(NEXT_PAGE_JS, pageno):
            break
        time.sleep(2)
    if got:
        json.dump(meta, open(mf, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        log(f'剧目元信息 {got} 条（含上线时间）-> drama_meta.json')


def data_date(page):
    """页面顶部官方标注 'data updated to YYYY-MM-DD'（中文界面为"数据更新至"）
    = 本次导出数据的真实截止日。平台数据滞后 2~3 天且偶尔跳更，
    快照必须按数据日期归档，不能按导出日期。"""
    for _ in range(3):
        try:
            m = re.search(r'(?:data updated to|数据更新至)\s*(\d{4}-\d{2}-\d{2})',
                          page.inner_text('body'))
            if m:
                return m.group(1)
        except Exception:
            pass
        time.sleep(2)
    return None


def sync_s3(today):
    """report.html 推到团队 S3 固定 key（config: s3_report_path，相对 aigc/drama/）。
    覆盖同一 key，外部引用链接保持不变。凭证用 config.json 的 s3_ak/s3_sk
    或环境变量 S3_UPLOAD_AK/S3_UPLOAD_SK。未配置则跳过，失败不影响主流程。"""
    rel = CFG.get('s3_report_path', '').strip().strip('/')
    if not rel:
        return
    try:
        import boto3
        from botocore.config import Config as BotoConfig
        ak = CFG.get('s3_ak') or os.environ.get('S3_UPLOAD_AK')
        sk = CFG.get('s3_sk') or os.environ.get('S3_UPLOAD_SK')
        kw = {'aws_access_key_id': ak, 'aws_secret_access_key': sk} if ak and sk else {}
        s3 = boto3.client('s3', region_name='us-east-1',
                          config=BotoConfig(signature_version='s3v4'), **kw)
        key = f'aigc/drama/{rel}/report.html'
        # ContentType 不设会被当附件下载；no-cache 保证每天刷新后立即生效
        s3.upload_file(os.path.join(BASE, 'report.html'), 'starlitshorts', key,
                       ExtraArgs={'ContentType': 'text/html; charset=utf-8',
                                  'CacheControl': 'no-cache'})
        log(f'S3 已同步 s3://starlitshorts/{key}')
    except Exception as e:
        log(f'S3 同步失败（不影响主流程）: {e}')


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

            dd = data_date(page)
            daily = page.evaluate(EXTRACT_JS)
            if not dd and daily:
                dd = daily[-1]['eventDate']  # 趋势最后一天=数据截止日，语言无关的兜底
                log(f'未找到 "data updated to" 标注，用趋势最后一天兜底: {dd}')
            if not dd:
                log('警告：标注和趋势都没拿到，退回用导出日期命名。')
                dd = today
            elif os.path.exists(os.path.join(DATA, f'content_performance_{dd}.xlsx')):
                log(f'平台数据未刷新（仍截止 {dd}，快照已存在），本次跳过。')
                return 0
            else:
                log(f'平台数据截止日: {dd}')

            # 1) 导出 xlsx（直接接住下载，不经过下载目录）
            xlsx = os.path.join(DATA, f'content_performance_{dd}.xlsx')
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
            # 平台刷新不是原子的：刚翻到新数据日时导出可能只含一部分剧（实测出现过 22->14）。
            # 剧目数比上一份快照少 2 部以上视为残缺，丢弃本次，等下一轮定时重试。
            import glob as _g
            import openpyxl as _o
            def _rows(f):
                return sum(1 for r in _o.load_workbook(f).active.iter_rows(min_row=2, values_only=True) if r[0])
            prev = sorted(f for f in _g.glob(os.path.join(DATA, 'content_performance_*.xlsx')) if f != xlsx)
            if prev:
                n_new, n_prev = _rows(xlsx), _rows(prev[-1])
                if n_new <= n_prev - 2:
                    os.remove(xlsx)
                    log(f'导出疑似残缺（{n_new} 部剧，上一份 {n_prev} 部），已丢弃，下一轮自动重试。')
                    notify(f'【TikTok短剧日报】{dd} 的导出只有 {n_new} 部剧（上次 {n_prev} 部），'
                           '平台可能正在刷新中，本次未入库，下一轮定时任务会自动重试。')
                    return 3
            log(f'快照已保存 {os.path.basename(xlsx)} ({os.path.getsize(xlsx)} bytes)')
            try:
                collect_meta(page)
            except Exception as e:
                log(f'剧目元信息抓取失败（不影响主流程）: {e}')

            # 2) 每日趋势（上面已顺带提取）
            if not daily:
                log('警告：未能从页面状态提取每日趋势（页面结构可能变了），跳过该数据源。')
            else:
                jf = os.path.join(DATA, f'daily_stats_{dd}.json')
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
    # 数据校验：报告必须包含本次快照的数据日期
    if dd not in open(os.path.join(BASE, 'report.html'), encoding='utf-8').read():
        log(f'警告：report.html 中未找到本次数据日期 {dd}。')

    # 4) 可选推送（先 pull --rebase，避免和别的机器互相顶掉）
    if push:
        for cmd in (['git', 'pull', '--rebase', '--autostash'],
                    ['git', 'add', 'data', 'report.html'],
                    ['git', 'commit', '-m', f'data: snapshot {dd} (exported {today})'],
                    ['git', 'push']):
            r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
            if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
                log(f'git 失败: {" ".join(cmd)}\n{r.stderr.strip()}')
                return 4
        log('已推送到远端。')
        sync_pages_repo(today)
        sync_s3(today)
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
