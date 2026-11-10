"""Collect the November analytics page through its UI and observed responses.

No direct/signed API calls. Legacy snapshots remain immutable; v2 stores explicit
date intervals and IDs from the page, never the lagging cumulative XLSX columns.
"""
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import time


class PageDataError(RuntimeError):
    pass


def error_kind(reason):
    if re.match(r'^(?:机构趋势|剧目第 \d+ 页)失败：.*HTTP \d+', reason):
        return 'platform_error'
    return 'unverified'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    # Corruption must never silently erase accepted history.
    return json.loads(path.read_text(encoding='utf-8'))


def shift(day, n):
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def date_axis(start, end):
    return [shift(start, i) for i in range((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1)]


def number(metrics, key):
    value = metrics.get(key)
    if value is None or value == '':
        raise PageDataError(f'页面缺少指标 {key}，不能按 0 入库')
    n = int(value)
    if n < 0:
        raise PageDataError(f'页面指标 {key} 为负数: {n}')
    return n


def normalize_block(block):
    m, info = block.get('aggregatedMetrics', {}), block.get('contractInfo', {})
    did = str(block.get('contractID') or '')
    if not did or not info.get('contractTitle'):
        raise PageDataError('剧目缺少稳定 ID 或名称')
    pub = info.get('publishTimeSec')
    return dict(
        id=did, name=info['contractTitle'],
        launch=dt.datetime.fromtimestamp(int(pub), dt.timezone.utc).date().isoformat() if pub else None,
        episodes=info.get('episodeNum'), duration=info.get('durationSec'),
        qv=number(m, 'innerfeedVvDelta'), like=number(m, 'likeCntDelta'),
        com=number(m, 'commentCntDelta'), fav=number(m, 'favouriteCntDelta'),
        cumulative=dict(qv=number(m, 'innerfeedVv'), like=number(m, 'likeCnt'),
                        com=number(m, 'commentCnt'), fav=number(m, 'favouriteCnt'),
                        dur=float(m['avgPlayDurationPerUser']) if m.get('avgPlayDurationPerUser') is not None else None),
    )


def validate_range(start, end, daily_data, pages):
    """Completeness, stable IDs, date coverage and exact reconciliation."""
    if (daily_data.get('actualDateRangeStart'), daily_data.get('actualDateRangeEnd')) != (start, end):
        raise PageDataError(f'机构趋势返回的日期区间不匹配 {start} ~ {end}')
    latest = daily_data.get('latestEventDate')
    if not latest or end > latest:
        raise PageDataError('所选日期超过平台最新数据日')
    daily = {r['eventDate']: number(r.get('metrics', {}), 'innerfeedVv') for r in daily_data.get('dailyRows', [])}
    if len(daily) != len(daily_data.get('dailyRows', [])) or set(daily) != set(date_axis(start, end)):
        raise PageDataError(f'{start} ~ {end} 的机构趋势有缺日/重复日期，拒绝补零')
    if not pages:
        raise PageDataError('剧目分页未返回')
    total = int(pages[0]['total'])
    contract_cutoff = pages[0].get('latestEventDate')
    if not contract_cutoff or contract_cutoff < end:
        raise PageDataError('剧目数据的可用截止日早于所选区间，拒绝按完整区间入库')
    if any(int(p['total']) != total or p.get('latestEventDate') != contract_cutoff for p in pages):
        raise PageDataError('分页期间剧目总数或数据截止日发生变化')
    blocks = [b for p in pages for b in p.get('contractBlocks', [])]
    rows = [normalize_block(b) for b in blocks]
    if len(rows) != total or len({r['id'] for r in rows}) != total:
        raise PageDataError(f'分页残缺或 ID 重复：期望 {total} 部，实际 {len(rows)} 部')
    expected = sum(daily.values())
    summary = number(daily_data.get('summary', {}), 'innerfeedVvDelta')
    actual = sum(r['qv'] for r in rows)
    if expected != summary or actual != expected:
        raise PageDataError(f'{start} ~ {end} 对账失败：剧目增量 {actual:,} / 日趋势 {expected:,} / 区间汇总 {summary:,}')
    return dict(schema=2, source='page_v2', start=start, end=end, asOf=latest, contractAsOf=contract_cutoff,
                checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                audit=dict(status='ok', rows=total, dramaQv=actual, trendQv=expected, deviation=0),
                daily=daily, rows=rows,
                institutionCumulative=number(daily_data['summary'], 'innerfeedVv'))


class PageCapture:
    def __init__(self, page):
        self.page = page
        self.daily = {}
        self.pages = {}
        self.errors = []
        self.failures = {}
        page.on('response', self.response)

    def close(self):
        self.page.remove_listener('response', self.response)

    def response(self, response):
        # Observe the site's own browser requests; never save signed URLs/cookies.
        path = response.url.split('?', 1)[0]
        if '/analytics/v2/institution/' not in path:
            return
        try:
            request = response.request.post_data_json
            if path.endswith('/daily-stats'):
                bounds = request['dateRange']
                key = (bounds['startDate'], bounds['endDate'])
            elif path.endswith('/contract-stats-list'):
                key = (request['startDate'], request['endDate'], int(request['pageNum']))
            else:
                return
            obj = response.json()
            if response.status != 200 or obj.get('code') != 0:
                error = f'{path.rsplit("/", 1)[-1]} HTTP {response.status} code {obj.get("code")}'
                self.errors.append(error)
                self.failures[key] = error
                return
            self.failures.pop(key, None)
            data = obj['data']
            if path.endswith('/daily-stats'):
                bounds = request['dateRange']
                self.daily[(bounds['startDate'], bounds['endDate'])] = data
            elif path.endswith('/contract-stats-list'):
                # Refuse silently inherited user filters.
                allowed = {'startDate', 'endDate', 'pageNum', 'pageSize'}
                if any(v not in (None, '', [], {}) for k, v in request.items() if k not in allowed):
                    self.errors.append('剧目请求含非默认筛选，拒绝按全机构入库')
                    return
                self.pages[(request['startDate'], request['endDate'], int(request['pageNum']))] = (
                    data, int(request['pageSize']))
        except Exception as e:
            error = f'页面响应解析失败：{type(e).__name__}'
            self.errors.append(error)
            if 'key' in locals():
                self.failures[key] = error

    def wait(self, predicate, what, timeout=30000, key=None):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if predicate():
                return
            if key in self.failures:
                raise PageDataError(f'{what}失败：{self.failures[key]}')
            self.page.wait_for_timeout(100)
        raise PageDataError(f'等待{what}超时；' + '；'.join(self.errors[-3:]))

    def select_dates(self, start, end):
        page = self.page
        page.get_by_role('button', name='Date range').click()
        page.locator('.semi-datepicker-month-grid-left:visible').wait_for()
        for target in (start, end):
            for _ in range(25):
                # The two calendar panels navigate independently (Sep / Nov is
                # possible). Always navigate the left panel, not global bounds.
                calendar = page.locator('.semi-datepicker-month-grid-left:visible')
                cell = calendar.get_by_role('gridcell', name=target, exact=True)
                if cell.count() and cell.first.is_visible():
                    if cell.first.get_attribute('aria-disabled') == 'true':
                        raise PageDataError(f'平台不允许选择 {target}')
                    cell.first.evaluate('(el) => el.click()')
                    page.wait_for_timeout(100)
                    break
                visible = calendar.locator('[role="gridcell"][title]').evaluate_all(
                    '(es)=>es.filter(e=>e.getClientRects().length).map(e=>e.title).sort()')
                if not visible:
                    raise PageDataError('日期选择器结构改变')
                direction = 'Previous month' if target < visible[0] else 'Next month'
                calendar.get_by_role('button', name=direction, exact=True).evaluate('(el) => el.click()')
                page.wait_for_timeout(100)
            else:
                raise PageDataError(f'无法定位日历日期 {target}')
        page.get_by_role('button', name='Confirm', exact=True).click()
        page.wait_for_timeout(100)

    def collect(self, start, end):
        # One ordinary UI retry for intermittent server errors. Preserve the
        # error if both attempts fail; do not loosen any data checks.
        for attempt in range(2):
            try:
                return self._collect(start, end)
            except PageDataError as e:
                if attempt or not re.search(r'HTTP 5\d\d', str(e)):
                    raise
                self.daily.pop((start, end), None)
                for key in list(self.pages):
                    if key[:2] == (start, end):
                        self.pages.pop(key)
                self.page.wait_for_timeout(500)
                retries = self.page.get_by_text('Retry', exact=True)
                if retries.count():
                    retries.evaluate_all('(es) => es.forEach(el => el.click())')
                else:
                    self.page.reload(wait_until='domcontentloaded')
                    self.page.get_by_role('button', name='Export', exact=True).wait_for(timeout=30000)

    def _collect(self, start, end):
        self.current_range = (start, end)
        self.failures.pop((start, end), None)
        for key in list(self.failures):
            if key[:2] == (start, end):
                self.failures.pop(key, None)
        self.select_dates(start, end)
        self.wait(lambda: (start, end) in self.daily, '机构趋势', key=(start, end))
        # New UI retains the previously selected page when dates change.
        if (start, end, 1) not in self.pages:
            self.click_page(1)
        self.wait(lambda: (start, end, 1) in self.pages, '剧目第 1 页', key=(start, end, 1))
        first, page_size = self.pages[(start, end, 1)]
        pages = [first]
        for n in range(2, math.ceil(int(first['total']) / page_size) + 1):
            self.click_page(n)
            self.wait(lambda: (start, end, n) in self.pages, f'剧目第 {n} 页', key=(start, end, n))
            pages.append(self.pages[(start, end, n)][0])
        record = validate_range(start, end, self.daily[(start, end)], pages)
        # Some date ranges have fewer pages; leaving page 4 selected makes the
        # site's next query fail and hides its pagination. Reset before moving.
        if int(first['total']) > page_size:
            self.click_page(1)
        return record

    def click_page(self, number):
        # Same DOM click as the legacy NEXT_PAGE_JS. Pagination may temporarily be
        # hidden by the site's out-of-range-page error; its handler still works.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            found = self.page.evaluate('''(n) => {
              const el = [...document.querySelectorAll('.semi-page-item')].find(e => e.textContent.trim() === String(n));
              if (!el) return false;
              el.click(); return true;
            }''', number)
            if found:
                return
            failure = self.failures.get((*self.current_range, number))
            if failure:
                raise PageDataError(f'剧目第 {number} 页失败：{failure}')
            self.page.wait_for_timeout(100)
        raise PageDataError(f'页面缺少第 {number} 页的分页入口；' + '；'.join(self.errors[-2:]))


def needs_refresh(existing, day, latest, refresh_days, institution):
    return (not existing or existing.get('audit', {}).get('status') != 'ok'
            or day >= shift(latest, 1-refresh_days)
            or existing.get('audit', {}).get('trendQv') != institution.get(day))


def save_day(path, record):
    old = read_json(path)
    def increments(r):
        return {row['id']: tuple(row[k] for k in ('qv', 'like', 'fav', 'com')) for row in r['rows']}
    if old and (increments(old) != increments(record) or old['audit']['trendQv'] != record['audit']['trendQv']):
        stamp = old['checked'].replace(':', '').replace('+', '_')
        atomic_json(Path(path).parent.parent / 'revisions' / Path(path).stem / f'{stamp}.json', old)
    atomic_json(path, record)


def check_record(record):
    if record.get('schema') != 2 or record.get('source') != 'page_v2':
        raise PageDataError('不认识的数据格式或来源')
    start, end = record['start'], record['end']
    if (start > end or end > record['asOf'] or end > record.get('contractAsOf', record['asOf'])
            or set(record['daily']) != set(date_axis(start, end))):
        raise PageDataError('日期边界或日趋势覆盖不正确')
    rows, audit = record['rows'], record['audit']
    if len(rows) != len({r['id'] for r in rows}) or any(not r['id'] for r in rows):
        raise PageDataError('剧目 ID 缺失/重复')
    values = list(record['daily'].values()) + [r[k] for r in rows for k in ('qv', 'like', 'com', 'fav')]
    if any(type(v) is not int or v < 0 for v in values):
        raise PageDataError('增量不是非负整数')
    actual, expected = sum(r['qv'] for r in rows), sum(record['daily'].values())
    if (actual != expected or audit.get('status') != 'ok' or audit.get('rows') != len(rows)
            or audit.get('dramaQv') != actual or audit.get('trendQv') != expected or audit.get('deviation') != 0):
        raise PageDataError('存档重新计算后不满足验收条件')


def period_checks(root, manifest):
    checks = {}
    for label, name in manifest['periods'].items():
        period = read_json(Path(root) / 'periods' / name)
        axis = date_axis(period['start'], period['end'])
        missing = [d for d in axis if not (Path(root) / 'days' / f'{d}.json').exists()]
        if missing:
            checks[label] = dict(status='incomplete', missing=missing)
            continue
        sums = {}
        for day in axis:
            record = read_json(Path(root) / 'days' / f'{day}.json')
            check_record(record)
            for row in record['rows']:
                item = sums.setdefault(row['id'], {k: 0 for k in ('qv', 'like', 'com', 'fav')})
                for k in item:
                    item[k] += row[k]
        expected = {r['id']: r for r in period['rows']}
        differences = []
        for did in sorted(set(expected) | set(sums)):
            for field in ('qv', 'like', 'com', 'fav'):
                a, b = sums.get(did, {}).get(field, 0), expected.get(did, {}).get(field, 0)
                if a != b:
                    differences.append(dict(id=did, field=field, daily=a, period=b))
        checks[label] = dict(status='different' if differences else 'ok', days=len(axis),
                             differences=differences,
                             totals={k: sum(r[k] for r in sums.values()) for k in ('qv', 'like', 'com', 'fav')})
    return checks


def audit_data(base):
    """Read-only audit: recompute all records, then cross-check measured intervals."""
    root = Path(base) / 'data' / 'v2'
    manifest = read_json(root / 'latest.json')
    errors = []
    institution = read_json(root / 'institution_daily.json')
    files = sorted((root / 'days').glob('*.json')) + sorted((root / 'periods').glob('*.json'))
    for path in files:
        try:
            record = read_json(path)
            check_record(record)
            expected_name = record['start'] if path.parent.name == 'days' else f'{record["start"]}_{record["end"]}'
            if path.stem != expected_name or (path.parent.name == 'days' and record['start'] != record['end']):
                raise PageDataError('文件名与数据区间不一致')
            if path.parent.name == 'days' and institution.get(record['end']) != record['audit']['trendQv']:
                raise PageDataError('单日存档与当前机构趋势修订值不一致，待重采')
        except Exception as e:
            errors.append(f'{path.name}: {e}')
    for label, name in manifest['periods'].items():
        try:
            if read_json(root / 'periods' / name)['asOf'] != manifest['latest']:
                raise PageDataError('当前报告区间截止日不一致')
        except Exception as e:
            errors.append(f'{label}: {e}')
    try:
        for label, check in period_checks(root, manifest).items():
            if check['status'] == 'different':
                errors.append(f'{label} 逐日/整段指标不一致: {check["differences"][:3]}')
    except Exception as e:
        errors.append(str(e))
    return len(files), errors


def collect(page, base, latest=None, log=print, backfill_days=30, refresh_days=3,
            history_start=None, retry_hours=24):
    """Refresh recent days and backfill missing direct daily records, atomically."""
    root = Path(base) / 'data' / 'v2'
    capture = PageCapture(page)
    try:
        if not 1 <= backfill_days <= 180 or not 1 <= refresh_days <= backfill_days:
            raise ValueError('v2_backfill_days 必须为1~180，v2_refresh_days 必须为1~补采天数')
        # Reload once so all initial responses are observed (open_page did goto).
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('button', name='Export', exact=True).wait_for(timeout=30000)
        if latest is None:
            # Date filters persist in the profile, including a range the server
            # cannot load. Restore a supported shortcut before reading freshness.
            page.get_by_role('button', name='Date range').click()
            page.get_by_text('Last 30 days', exact=True).click()
            page.get_by_role('button', name='Confirm', exact=True).click()
            capture.wait(lambda: bool(capture.daily), '最新机构趋势')
            latest = max(r['latestEventDate'] for r in capture.daily.values())
        periods, unavailable = {}, {}
        prior_manifest = read_json(root / 'latest.json', {})
        for days in (7, 30):
            for previous in (False, True):
                end = shift(latest, -days) if previous else latest
                start = shift(end, 1-days)
                label = ('previous' if previous else 'last') + str(days)
                if label == 'previous30' and prior_manifest.get('latest') == latest and prior_manifest.get('unavailablePeriods', {}).get(label):
                    unavailable[label] = prior_manifest['unavailablePeriods'][label]
                    continue
                try:
                    record = capture.collect(start, end)
                except PageDataError as e:
                    if label != 'previous30':
                        raise
                    unavailable[label] = dict(start=start, end=end, reason=str(e))
                    log(f'前30日暂不可用：{e}；保留近30日实测，不编造月环比')
                    continue
                atomic_json(root / 'periods' / f'{start}_{end}.json', record)
                periods[label] = f'{start}_{end}.json'
                log(f'新版 {label} {start} ~ {end}：{len(record["rows"])} 部，对账 {record["audit"]["trendQv"]:,}，精确相等')
        # This also provides a 60-day institution trend without synthesizing old metrics.
        institution = read_json(root / 'institution_daily.json', {})
        for filename in periods.values():
            institution.update(read_json(root / 'periods' / filename)['daily'])
        atomic_json(root / 'institution_daily.json', institution)
        requested_start = history_start or shift(latest, 1-backfill_days)
        if dt.date.fromisoformat(requested_start) > dt.date.fromisoformat(latest):
            raise ValueError('历史起始日期晚于最新数据日')
        history_status = read_json(root / 'history_status.json', {})
        failed_days, consecutive_failures = {}, 0
        for day in reversed(date_axis(requested_start, latest)):
            path = root / 'days' / f'{day}.json'
            existing = read_json(path)
            if not needs_refresh(existing, day, latest, refresh_days, institution):
                continue
            prior_failure = history_status.get(day)
            if prior_failure and not existing and day < shift(latest, 1-refresh_days):
                elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(prior_failure['checked'])
                if elapsed.total_seconds() < retry_hours * 3600:
                    failed_days[day] = prior_failure['reason']
                    continue
            try:
                record = capture.collect(day, day)
            except PageDataError as e:
                failed_days[day] = str(e)
                history_status[day] = dict(reason=str(e), kind=error_kind(str(e)),
                                          checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
                atomic_json(root / 'history_status.json', history_status)
                institution_only = capture.daily.get((day, day))
                if institution_only:
                    try:
                        rows = institution_only['dailyRows']
                        if (institution_only['actualDateRangeStart'] != day or institution_only['actualDateRangeEnd'] != day
                                or len(rows) != 1 or rows[0]['eventDate'] != day):
                            raise PageDataError('机构日期不完整')
                        qv = number(rows[0]['metrics'], 'innerfeedVv')
                        if qv != number(institution_only['summary'], 'innerfeedVvDelta'):
                            raise PageDataError('机构汇总不一致')
                        institution[day] = qv
                        atomic_json(root / 'institution_daily.json', institution)
                    except (KeyError, PageDataError):
                        pass
                log(f'单日 {day} 未通过验收：{e}；留空并在后续轮次重试')
                if day == latest:
                    raise
                consecutive_failures += 1
                if consecutive_failures >= 3 and not history_start:
                    log('连续3个历史日期无法获取，停止本轮补采；已验收日期保留')
                    break
                continue
            consecutive_failures = 0
            save_day(path, record)
            institution.update(record['daily'])
            atomic_json(root / 'institution_daily.json', institution)
            if day in history_status:
                history_status.pop(day)
                atomic_json(root / 'history_status.json', history_status)
            log(f'新版单日 {day}：{len(record["rows"])} 部，合格播放 {record["audit"]["trendQv"]:,}，精确对账通过')
        # Manifest advances only when every required period/day passed validation.
        manifest = dict(schema=2, latest=latest, periods=periods,
                        backfillDays=backfill_days, requestedStart=requested_start,
                        unavailablePeriods=unavailable, failedDays=failed_days,
                        checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
        checks = period_checks(root, manifest)
        redo = set()
        for label, check in checks.items():
            if check['status'] == 'different':
                period = read_json(root / 'periods' / periods[label])
                redo.update(date_axis(period['start'], period['end']))
        if redo:
            log(f'逐日与整段指标存在修订差异，重新采集 {len(redo)} 个日期后再验收')
            for day in sorted(redo, reverse=True):
                record = capture.collect(day, day)
                save_day(root / 'days' / f'{day}.json', record)
                institution.update(record['daily'])
            atomic_json(root / 'institution_daily.json', institution)
            checks = period_checks(root, manifest)
        if any(c['status'] == 'different' for c in checks.values()):
            raise PageDataError('逐日与整段指标在重采后仍不一致，报告保留上次已验收版本')
        manifest['periodChecks'] = checks
        atomic_json(root / 'latest.json', manifest)
        return manifest
    finally:
        capture.close()
