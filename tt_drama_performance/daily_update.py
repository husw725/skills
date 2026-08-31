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


# ---- 快照验收台账 --------------------------------------------------------
# 老逻辑的跳过判定只看"这个数据日的文件在不在"，于是一份半刷新快照一旦入库就被永久
# 冻住、后续每一轮都跳过（2026-08-18 实测因此漏掉 08-19 的单日切分）。现在每份快照都
# 必须过对账验收并登记在册，只有"验收通过"的数据日才允许跳过。
AUDIT = os.path.join(DATA, 'snapshot_audit.json')
QUAR = os.path.join(DATA, '_quarantine')
# 反推真实截止日的匹配容差。平台日界切分有漂移，实测最大 ±6.8%（08-09/08-10 两天，
# 且符号相反、两天合计只差 0.04%，属于量在日界间挪动、不是丢数）。而相邻候选区间之间
# 相差约一整天的量（≈100%），所以 10% 既容得下漂移又不会把两天认混。
MATCH_TOL = 0.10
CLEAN_TOL = 0.03      # 这个偏差内记 ok，超了记 smear（已验收但有日界漂移）


def snap_rows(f):
    """{contract_id: dict(name, qv, tv, ...)}，按列名读（见 generate_report.HDR）。
    对账探针用 qv（合格播放）：2026-08-24 起导出没有总播放列了，而趋势里的 innerfeedVv
    与它同口径，历史各档偏差同样 <0.2%。"""
    from generate_report import read_snapshot
    return read_snapshot(f)


TREND_KEY = 'innerfeedVv'   # 趋势 metrics 里与导出"合格播放"同口径的字段
HIST_KEY = 'qv'             # daily_history.json 里对应的键


class AuditCorrupt(RuntimeError):
    """台账文件在，但读不出来。"""


def audit_load(strict=True):
    """读验收台账。**读不出来时绝不能当空台账返回。**

    跳过判定只认这个文件，空台账等于所有历史快照一起退回"未验收"：下一轮会把它们
    重新导出，还可能拿一份未验收的导出把已入库的好快照顶掉。2026-08-26 实测：
    autostash 落回冲突把冲突标记写进了这个 JSON，老逻辑 `except: return {}` 静默归零，
    27 档台账当场只剩 2 档。
    文件不存在才是合法的空（首次运行）；存在但解析失败一律抛出，由 __main__ 的总闸
    告警退出，坏文件原样留在盘上等人工处理。
    strict=False 只给 audit_all 用——它本身就是重建台账的修复工具。
    """
    if not os.path.exists(AUDIT):
        return {}
    try:
        with open(AUDIT, encoding='utf-8') as fh:
            au = json.load(fh)
        if not isinstance(au, dict):
            raise ValueError(f'顶层不是 dict 而是 {type(au).__name__}')
        return au
    except Exception as e:
        msg = (f'验收台账 {os.path.basename(AUDIT)} 在，但读不出来'
               f'（{e.__class__.__name__}: {str(e)[:120]}）。拒绝按空台账继续，'
               f'否则已验收的历史快照会被全部重采。修法：先解开 git 冲突，'
               f'再跑 python daily_update.py --audit 重建。')
        if strict:
            raise AuditCorrupt(msg) from e
        log(f'{msg}（--audit 本身就是重建工具，按空台账继续）')
        return {}


def audit_save(a):
    """先写临时文件再原子替换——半截的台账和读不出来的台账一样致命（见 audit_load）。"""
    tmp = AUDIT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(a, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, AUDIT)


def same_scope_delta(new_rows, prev_rows):
    """同口径增量（只算两份快照都在的剧）+ 新增/消失名单。

    必须同口径：平台会把存量老剧新纳入统计，这类剧首现带的是全量历史累计
    （实测 +1,730,722），混进全行求和会把偏差冲爆（08-18 那次 148.6%），
    反而盖掉"老剧一部都没刷新"这个真问题。
    """
    common = set(new_rows) & set(prev_rows)
    return (sum((new_rows[k]['qv'] or 0) - (prev_rows[k]['qv'] or 0) for k in common),
            sorted(set(new_rows) - set(prev_rows)),
            sorted(set(prev_rows) - set(new_rows)),
            len(common))


def true_cutoff(sdiff, tm, prev_dd, dd):
    """反推快照的真实截止日：同口径增量 ≈ 官方趋势 (prev_dd, X] 区间和 的那个 X。

    平台会先把"数据更新至"翻到 dd、剧目行晚一天才补（2026-08-18 实测），所以标注日
    不可信，只有对账反推出来的 X 才是这份快照真正覆盖到的日子。按 X 命名文件，
    页面上那种"标 1 天、实际装两天"的错位就不会再发生。返回 (X, 区间和, 偏差) 或 None。
    """
    run = 0
    for x in sorted(d for d in tm if prev_dd < d <= dd):
        run += tm[x]
        if run > 0 and abs(sdiff - run) / run <= MATCH_TOL:
            return x, run, (sdiff - run) / run
    return None


def audit_all(write=True):
    """离线全量复查（不开浏览器）：把每一份已入库快照拿去和官方趋势对账，重建台账。

    用途：①一次性给历史快照补验收记录，避免定时任务把它们全部重新导出一遍；
    ②随时体检——列出所有对不上的区间和缺采日期。返回 (台账, 问题清单)。
    """
    import glob as _g
    snaps = {}
    for f in sorted(_g.glob(os.path.join(DATA, 'content_performance_*.xlsx'))):
        if '.candidate.' in os.path.basename(f):
            continue
        snaps[re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(f)).group(1)] = f
    try:
        hist = json.load(open(os.path.join(DATA, 'daily_history.json'), encoding='utf-8'))
    except Exception:
        log('daily_history.json 读不到，无法对账。')
        return {}, []
    tm = {k: int(v.get(HIST_KEY, 0)) for k, v in hist.items()}
    ds = sorted(snaps)
    au, problems = audit_load(strict=False), []
    log(f'全量复查：{len(ds)} 份快照 {ds[0]} ~ {ds[-1]}，趋势覆盖 {min(tm)} ~ {max(tm)}')
    for i in range(1, len(ds)):
        a, b = ds[i - 1], ds[i]
        prev_r, new_r = snap_rows(snaps[a]), snap_rows(snaps[b])
        sdiff, added, gone, ncommon = same_scope_delta(new_r, prev_r)
        days = (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
        tsum = sum(v for d, v in tm.items() if a < d <= b)
        dev = (sdiff - tsum) / tsum if tsum else None
        hit = true_cutoff(sdiff, tm, a, b)
        if dev is None:
            st = 'unverified'
        elif hit and hit[0] != b:
            st = 'mislabelled'    # 文件名的日期不是它真实覆盖到的日子
        elif not hit:
            st = 'unresolved'     # 对不上任何一天的区间和 = 半刷新
        else:
            st = 'ok' if abs(dev) <= CLEAN_TOL else 'smear'
        au[b] = dict(status=st, label=b, sdiff=sdiff, tsum=tsum, dev=dev, days=days,
                     rows=len(new_r), base=a,
                     checked=datetime.datetime.now().isoformat(timespec='seconds'))
        mark = '' if st in ('ok', 'smear') else f'   <== {st}'
        log(f'  {a}->{b} {days}天  同口径 {sdiff:>12,}  趋势 {tsum:>12,}  '
            f'{dev:+7.2%}  {len(new_r)}部  +{len(added)}/-{len(gone)}  {st}{mark}')
        if st not in ('ok', 'smear'):
            problems.append((a, b, st, sdiff, tsum))
        if days > 1:
            miss = [(datetime.date.fromisoformat(a) + datetime.timedelta(days=k)).isoformat()
                    for k in range(1, days)]
            log(f'      缺采（平台未单独下发，永久取不到）: {"、".join(miss)}')
    if write:
        audit_save(au)
        log(f'台账已写入 {os.path.basename(AUDIT)}（{len(au)} 条）')
    gaps = [d for d in sorted(tm) if ds[0] < d <= ds[-1] and d not in snaps]
    log(f'剧目级缺单日切分的日期: {"、".join(gaps) if gaps else "无"}')
    log(f'对不上的区间: {len(problems)} 个' + (f' -> {problems}' if problems else ''))
    return au, problems


def quarantine(src, dd, why):
    """驳回的导出不删除，挪进 data/_quarantine/ 留证（本地取证用，已 gitignore）。
    关键是把数据日文件名腾出来——被坏文件占住的数据日会被跳过逻辑永久堵死。"""
    os.makedirs(QUAR, exist_ok=True)
    dst = os.path.join(QUAR, f'{dd}__{datetime.datetime.now():%m%d-%H%M%S}__{why}.xlsx')
    try:
        os.replace(src, dst)
    except OSError:
        try:
            os.remove(src)
        except OSError:
            pass
        return None
    return dst


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


ALERT = os.path.join(DATA, '.alert_state.json')


def _alert_state():
    try:
        with open(ALERT, encoding='utf-8') as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _alert_write(st):
    try:
        with open(ALERT, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError as e:
        log(f'告警状态写入失败（不影响主流程）: {e}')


def notify_once(key, text, hours=12):
    """同一个故障 hours 小时内只推一条。定时任务 4 小时一轮，一个卡死状态能连推几十条
    （2026-08-26 那次卡了 5 天 = 30 轮），推成噪音就等于没推。"""
    st = _alert_state()
    now = datetime.datetime.now()
    try:
        last = datetime.datetime.fromisoformat(st[key]) if key in st else None
    except ValueError:
        last = None                      # 记号写坏了就当没推过，宁可多推一条
    if last and (now - last).total_seconds() < hours * 3600:
        log(f'（{key} 告警 {hours}h 内已推过，本次只记日志）')
        return
    notify(text)
    st[key] = now.isoformat(timespec='seconds')
    _alert_write(st)


def alert_clear(*keys):
    """故障恢复后清掉记号，下次再犯立刻能推出去（而不是被去重窗口吃掉）。"""
    st = _alert_state()
    if any(st.pop(k, None) is not None for k in keys):
        _alert_write(st)


# index 里的冲突状态码（git status --porcelain v1 的前两位）
CONFLICT_CODES = ('DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU')


def git_stuck():
    """检测仓库是不是卡在冲突/rebase 中间态；正常返回 None，否则返回一句人话。

    autostash 落回冲突时 index 里留 UU 但**没有** MERGE_HEAD，`git rebase --abort` 救不了，
    于是之后每一轮 pull 都是 "Pulling is not possible because you have unmerged files"：
    采集照常、git 全废。更糟的是"已验收就跳过"那条路径在 git 分发之前就 return 0 了，
    所以一条告警都发不出来——2026-08-26 起就这样静默卡了 5 天 30 轮，两份已验收快照
    一直没推出去。因此这个检查必须放在每轮最开头，与本轮有没有采到新数据无关。
    """
    gd = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=BASE,
                        capture_output=True, text=True)
    if gd.returncode != 0:
        return None                      # 不在 git 仓库里，交给调用方按普通 git 失败处理
    gdir = os.path.join(BASE, gd.stdout.strip())
    mid = [n for n in ('MERGE_HEAD', 'rebase-merge', 'rebase-apply', 'CHERRY_PICK_HEAD')
           if os.path.exists(os.path.join(gdir, n))]
    st = subprocess.run(['git', 'status', '--porcelain'], cwd=BASE,
                        capture_output=True, text=True)
    bad = [l for l in st.stdout.splitlines() if l[:2] in CONFLICT_CODES]
    if not mid and not bad:
        return None
    parts = []
    if bad:
        parts.append('未解决冲突 ' + '、'.join(l[3:] for l in bad[:5])
                     + (f' 等 {len(bad)} 个' if len(bad) > 5 else ''))
    if mid:
        parts.append('中间态 ' + '/'.join(mid))
    return '；'.join(parts)


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
    # 先 pull：另一台机器可能刚推过，不拉直接推会被 non-fast-forward 拒掉
    r = subprocess.run(['git', 'pull', '--rebase', '--autostash'],
                       cwd=d, capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(['git', 'rebase', '--abort'], cwd=d, capture_output=True)
    shutil.copyfile(os.path.join(BASE, 'report.html'), os.path.join(d, 'index.html'))
    for cmd in (['git', 'add', 'index.html'],
                ['git', 'commit', '-m', f'daily report {today}'],
                ['git', 'push']):
        r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
        if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
            log(f'分享页同步失败: {" ".join(cmd)} -> {r.stderr.strip()[:200]}')
            notify(f'【TikTok短剧日报】分享页(tt-drama-report)同步失败（{cmd[1]}），'
                   'github.io 短链暂未更新，下次数据更新时自动重试。')
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
                'launch': datetime.datetime.fromtimestamp(int(r['pub']), datetime.timezone.utc).date().isoformat(),
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
    # 仓库体检必须放在最前面：卡住时"已验收就跳过"那条路径会在 git 分发之前就 return，
    # 检查放后面等于永远发不出告警（2026-08-26 静默卡 5 天 30 轮的直接原因）。
    stuck = git_stuck() if push else None
    if push and not stuck:
        # 先同步远端：另一台机器可能已采过同一数据日，pull 后靠"快照已存在"直接跳过，
        # 避免两台机器各自持有同名未跟踪文件把 git 通道互相顶死
        r = subprocess.run(['git', 'pull', '--rebase', '--autostash'],
                           cwd=BASE, capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(['git', 'rebase', '--abort'], cwd=BASE, capture_output=True)
            log(f'预同步 pull 失败（继续本地采集）: {r.stderr.strip()[:200]}')
            first = (r.stderr.strip().splitlines() or ['见日志'])[0][:120]
            notify_once('git_pull',
                        f'【TikTok短剧日报】预同步 git pull 失败：{first}。'
                        '本轮继续本地采集，但远端可能已经落后，请检查 daily_update.log。')
        else:
            alert_clear('git_pull')
        # 复检 index：autostash 落不回去时 pull **照样返回 0**（已复现验证），
        # 只在 stdout 里留一行 "Applying autostash resulted in conflicts."。
        # 光看 returncode 就是 2026-08-26 那一轮什么都没报的原因。
        stuck = git_stuck()
    if stuck:
        # 采集不能因为 git 停：导出永远是"当前"全量累计，没有按历史日期回查的入口，
        # 错过当天的剧目级状态就永久找不回来。所以照常采集 + 传 S3，只禁掉 git 分发。
        push = False
        log(f'git 仓库卡在中间态（{stuck}），本轮禁用 git 分发，S3 与本地入库照常。')
        notify_once('git_stuck',
                    f'【TikTok短剧日报】git 仓库卡住了：{stuck}。数据照常采集、S3 照常更新，'
                    '但 GitHub 上的报告和数据备份已停止同步。修法：到仓库里 git status 看'
                    '冲突文件，解开后 git add + git commit；或 git merge --abort / '
                    'git rebase --abort 退回干净状态。')
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
            # ---- 跳过判定：只认"验收通过"的数据日 ----
            # 绝不能只看文件在不在。一份没过对账的快照必须允许后续轮次重新导出复查，
            # 否则平台补齐时我们已经跳过去了（2026-08-18 → 漏掉 08-19 单日切分）。
            au = audit_load()
            passed = {c for c, v in au.items() if v.get('status') in ('ok', 'smear')}
            if dd in passed:
                r = au[dd]
                log(f'{dd} 已验收通过（同口径偏差 {r["dev"]:+.2%}，{r["days"]}天档），本次跳过。')
                return 4 if stuck else 0
            log(f'平台数据截止日: {dd}')

            # 1) 导出 xlsx（直接接住下载，不经过下载目录）
            # 一律先落到 .candidate，验收通过才按"真实截止日"改名入库。已入库的好快照
            # 绝不能被一份未验收的导出覆盖。
            cand = os.path.join(DATA, f'content_performance_{dd}.candidate.xlsx')
            try:
                with page.expect_download(timeout=30000) as dl:
                    page.get_by_text('Export Data').first.click()
                dl.value.save_as(cand)
            except PWTimeout:
                log('导出失败：点击 Export Data 后 30 秒内没有产生下载。')
                notify('【TikTok短剧日报】导出失败（页面可能改版），今日数据未更新，请人工检查。')
                return 3
            if os.path.getsize(cand) < 1000:
                size = os.path.getsize(cand)
                quarantine(cand, dd, 'tiny')
                log(f'导出文件异常（{size} bytes），已隔离，下一轮自动重试。')
                notify(f'【TikTok短剧日报】{dd} 导出文件异常（{size} bytes），本次未入库，下一轮自动重试。')
                return 3
            # ---- 验收：过了才入库，没过就隔离重试 ----
            import glob as _g
            stored = sorted(f for f in _g.glob(os.path.join(DATA, 'content_performance_*.xlsx'))
                            if '.candidate.' not in os.path.basename(f))
            new_r = snap_rows(cand)
            xlsx = os.path.join(DATA, f'content_performance_{dd}.xlsx')   # 默认按标注日命名
            if stored:
                base_f = stored[-1]
                base_dd = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(base_f)).group(1)
                prev_r = snap_rows(base_f)
                sdiff, added, gone, ncommon = same_scope_delta(new_r, prev_r)
                if added:
                    log(f'新纳入统计 {len(added)} 部剧（首现带全量累计，不计入对账）: '
                        + '、'.join(str(new_r[k][1]) for k in added))
                if gone:   # 剧目消失是异常，必须留痕，绝不静默少采
                    log(f'警告：{len(gone)} 部剧在本次导出中消失: '
                        + '、'.join(str(prev_r[k][1]) for k in gone))
                # ① 少采：剧目数比上一份少 2 部以上（实测出现过 22->14）
                if len(new_r) <= len(prev_r) - 2:
                    quarantine(cand, dd, 'short')
                    log(f'导出疑似残缺（{len(new_r)} 部剧，上一份 {len(prev_r)} 部），已隔离，下一轮自动重试。')
                    notify(f'【TikTok短剧日报】{dd} 的导出只有 {len(new_r)} 部剧（上次 {len(prev_r)} 部），'
                           '平台可能正在刷新中，本次未入库，下一轮定时任务会自动重试。')
                    return 3
                # ② 平台原地不动：与已入库的某份逐行相同，没有新信息。安静重试，不告警。
                if any(new_r == snap_rows(f) for f in stored[-3:]):
                    quarantine(cand, dd, 'same')
                    log(f'平台标注 {dd}，但剧目行与已入库快照逐行相同（尚未推进），本次不入库。')
                    return 0
                # ③ 反推真实截止日。标注日不可信（平台会先翻标注、剧目行晚一天才补），
                #    只有对账能定出这份快照真正覆盖到哪天。定不出来就是半刷新，隔离重试。
                if daily:
                    tm = {r['eventDate']: int(r['metrics'].get(TREND_KEY, 0)) for r in daily}
                    hit = true_cutoff(sdiff, tm, base_dd, dd)
                    if not hit:
                        cands = {}
                        run = 0
                        for x in sorted(d for d in tm if base_dd < d <= dd):
                            run += tm[x]
                            cands[x] = run
                        quarantine(cand, dd, 'unresolved')
                        log(f'对账定不出真实截止日：同口径增量 {sdiff:,}（{ncommon} 部共同剧目），'
                            f'候选区间 {", ".join(f"{k}={v:,}" for k, v in cands.items()) or "无"}。'
                            '判定为剧目行只刷了一部分，已隔离，下一轮自动重试。')
                        if au.get(dd, {}).get('status') != 'unresolved':   # 同一数据日只告警一次
                            notify(f'【TikTok短剧日报】{dd} 剧目行疑似只刷了一部分'
                                   f'（同口径增量 {sdiff:,}，对不上任何一天的趋势区间和）。'
                                   '本次未入库，后续每轮会继续重试直到对上。')
                        au[dd] = dict(status='unresolved', label=dd, sdiff=sdiff, dev=None,
                                      days=None, rows=len(new_r), base=base_dd,
                                      checked=datetime.datetime.now().isoformat(timespec='seconds'))
                        audit_save(au)
                        return 0
                    cutoff, tsum, dev = hit
                    if cutoff != dd:
                        log(f'注意：平台标注 {dd}，但对账显示这份快照实际只覆盖到 {cutoff}'
                            f'（同口径增量 {sdiff:,} = 趋势 {base_dd}→{cutoff} 区间和 {tsum:,}）。'
                            f'按真实截止日 {cutoff} 入库。')
                    xlsx = os.path.join(DATA, f'content_performance_{cutoff}.xlsx')
                    if os.path.exists(xlsx):   # 该真实截止日已入库过，本次没有新东西
                        quarantine(cand, dd, 'dup')
                        log(f'{cutoff} 已入库，本次导出无新增，不覆盖。')
                        return 0
                    days = (datetime.date.fromisoformat(cutoff) - datetime.date.fromisoformat(base_dd)).days
                    if days > 1:   # 中间的日子平台没单独给过，永久拿不到，必须留痕
                        miss = [(datetime.date.fromisoformat(base_dd)
                                 + datetime.timedelta(days=k)).isoformat() for k in range(1, days)]
                        log(f'缺采告知：{"、".join(miss)} 平台未单独下发，'
                            f'{base_dd}→{cutoff} 只能作为 {days} 天合计入库（导出无历史回查入口，'
                            '这些单日切分永久取不到）。报告会如实标注，不做日均摊派。')
                        notify(f'【TikTok短剧日报】剧目级缺 {"、".join(miss)} 的单日切分'
                               f'（平台与 {cutoff} 合并下发）。{days} 天合计已入库并在报告中标注，'
                               '不做日均摊派。')
                    au[cutoff] = dict(status='ok' if abs(dev) <= CLEAN_TOL else 'smear',
                                      label=dd, sdiff=sdiff, tsum=tsum, dev=dev, days=days,
                                      rows=len(new_r), base=base_dd,
                                      checked=datetime.datetime.now().isoformat(timespec='seconds'))
                    audit_save(au)
                    log(f'验收通过：{cutoff} 同口径增量 {sdiff:,} vs 趋势 {tsum:,}，偏差 {dev:+.2%}'
                        + ('（日界漂移，已记 smear）' if abs(dev) > CLEAN_TOL else ''))
                else:
                    # 趋势没抓到就没法对账。入库但不记验收通过，下一轮会重新导出复查——
                    # 绝不能让一份没验过的快照冒充合格品把这个数据日永久占住。
                    log(f'趋势数据缺失，{dd} 无法对账验收：先入库，下一轮会重新导出复查。')
                    au[dd] = dict(status='unverified', label=dd, sdiff=sdiff, dev=None, days=None,
                                  rows=len(new_r), base=base_dd,
                                  checked=datetime.datetime.now().isoformat(timespec='seconds'))
                    audit_save(au)
            os.replace(cand, xlsx)
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
        notify(f'【TikTok短剧日报】{dd} 数据已采集但报告生成失败（generate_report.py），'
               '线上报告未更新，请检查 daily_update.log。')
        return 4
    # 数据校验：报告必须包含本次快照的数据日期
    if dd not in open(os.path.join(BASE, 'report.html'), encoding='utf-8').read():
        log(f'警告：report.html 中未找到本次数据日期 {dd}。')

    # 4) 分发。S3 优先（业务系统的消费口），git/分享页其次——三路互不阻塞，
    #    GitHub 偶发连不上时 S3 照常更新。
    if push or stuck:
        sync_s3(dd)          # S3 是业务系统的消费口，git 卡住也得照常更新
    if stuck:
        log('git 仓库仍卡在中间态，本轮不做 git 分发（本地已入库，解开冲突后会一并补推）。')
        return 4
    if push:
        for cmd in (['git', 'pull', '--rebase', '--autostash'],
                    ['git', 'add', 'data', 'report.html'],
                    ['git', 'commit', '-m', f'data: snapshot {dd} (exported {today})'],
                    ['git', 'push']):
            r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
            if cmd[1] == 'pull' and r.returncode == 0:
                st2 = git_stuck()        # autostash 落不回去，pull 仍然 rc 0
                if st2:
                    log(f'pull 之后 index 变成冲突态（{st2}）：autostash 落不回去，'
                        f'本轮停止 git 分发（数据已入库并传 S3）。')
                    notify_once('git_stuck',
                                f'【TikTok短剧日报】git pull 的 autostash 落回时冲突：{st2}。'
                                '数据已采集并同步 S3，但 GitHub 同步已停。'
                                '修法：解开冲突后 git add + git commit（本地改动在 git stash list 里）。')
                    return 4
            if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
                if 'pull' in cmd:
                    # rebase 冲突时把仓库恢复干净，避免后续每轮都卡在 rebase 中间态
                    subprocess.run(['git', 'rebase', '--abort'], cwd=BASE, capture_output=True)
                log(f'git 失败: {" ".join(cmd)}\n{r.stderr.strip()}')
                notify_once('git_push',
                            f'【TikTok短剧日报】{dd} 数据已采集（S3 分发不受影响，结果见日志）；'
                            f'但 git 推送失败（{cmd[1]}），GitHub 报告和数据备份未更新，'
                            '下次采到新数据时会一并补推，持续失败请检查 daily_update.log。')
                return 4
        alert_clear('git_stuck', 'git_pull', 'git_push')
        log('已推送到远端。')
        sync_pages_repo(today)
    log('完成。')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--login', action='store_true', help='首次人工登录')
    ap.add_argument('--push', action='store_true', help='更新后 git 推送')
    ap.add_argument('--headless', action='store_true', help='无浏览器窗口运行')
    ap.add_argument('--audit', action='store_true',
                    help='离线全量复查已入库快照并重建验收台账（不开浏览器、不改数据）')
    a = ap.parse_args()
    if a.audit:
        _, probs = audit_all()
        sys.exit(1 if probs else 0)
    if a.login:
        with sync_playwright() as p:
            sys.exit(do_login(p))
    try:
        sys.exit(run(a.push or CFG['git_push'], a.headless or CFG['headless']))
    except SystemExit:
        raise
    except Exception as e:
        # 总闸：任何未预期异常（浏览器启动失败、goto 超时、解析崩溃…）都必须告警，
        # 无人值守的管道里静默失败比失败更糟
        import traceback
        traceback.print_exc()
        notify(f'【TikTok短剧日报】运行异常中止：{e.__class__.__name__}: {str(e)[:150]}。'
               '今日数据可能未更新，请检查 daily_update.log。')
        sys.exit(4)
