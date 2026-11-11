"""Archive the single-title page's historical daily curves through its UI.

The title page has a different availability window from institution analytics.
Curves are kept as a separate source; absent dates are never filled with zero.
"""
import datetime as dt
import copy
import math
from pathlib import Path
import re
import time

from analytics_v2 import PageCapture, PageDataError, atomic_json, check_record, date_axis, read_json, shift


def parse_curve(data, start, end, metric):
    if (data.get('start_date'), data.get('end_date')) != (start, end):
        raise PageDataError('单剧曲线返回的日期范围不匹配')
    result, seen = {}, set()
    points = data.get('points', [])
    if not isinstance(points, list):
        raise PageDataError('单剧曲线数据不是列表')
    for row in points:
        day = row['event_date']
        if not start <= day <= end or day in seen:
            raise PageDataError('单剧曲线日期越界或重复')
        seen.add(day)
        raw = row.get(metric)
        if raw is None:
            continue
        try:
            dt.date.fromisoformat(day)
            if metric == 'innerfeed_vv':
                if not (type(raw) is int or isinstance(raw, str) and re.fullmatch(r'\d+', raw)):
                    raise ValueError('播放量不是整数')
                value = int(raw)
            else:
                value = float(raw)
        except (ValueError, TypeError) as e:
            raise PageDataError('单剧曲线包含无法解析的日期或数值') from e
        if value < 0 or not math.isfinite(value):
            raise PageDataError('单剧曲线包含非法数值')
        result[day] = value
    return result


class SeriesCapture:
    def __init__(self, page):
        self.page = page
        self.catalog, self.ranges, self.curves, self.failures = {}, {}, {}, {}
        self.total = None
        page.on('response', self.response)

    def close(self):
        self.page.remove_listener('response', self.response)

    def response(self, response):
        path = response.url.split('?', 1)[0]
        if '/api/content-partner/analytics/' not in path:
            return
        try:
            req = response.request.post_data_json
            obj = response.json()
            data = obj.get('data', {})
            if path.endswith('/institution/contract-stats-list') and not req.get('startDate'):
                if obj.get('code') == 0:
                    self.total = int(data['total'])
                    for block in data['contractBlocks']:
                        info = block.get('contractInfo', {})
                        self.catalog[str(block['contractID'])] = dict(name=info.get('contractTitle'),
                            episodes=info.get('episodeNum'), pub=info.get('publishTimeSec'))
                return
            if '/analytics/contract/' not in path:
                return
            did = str(req.get('contract_id') or '')
            if path.endswith('/data-range'):
                if response.status == 200 and obj.get('code') == 0 and str(data.get('contract_id')) == did:
                    self.ranges[did] = data
                else:
                    self.failures[(did, 'range')] = f'HTTP {response.status} code {obj.get("code")}'
                return
            metric = 'qv' if path.endswith('/chart/vv') else 'dur' if path.endswith('/chart/avg-play-duration') else None
            if not metric:
                return
            key = (did, req['start_date'], req['end_date'], metric)
            if response.status == 200 and obj.get('code') == 0:
                self.curves[key] = data
            else:
                self.failures[key] = f'HTTP {response.status} code {obj.get("code")}'
        except Exception:
            # Navigating to the next title can cancel an older response body.
            # Such a response supplies no data; the keyed wait will time out.
            pass

    def wait(self, predicate, key, timeout=15000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if predicate():
                return
            if key in self.failures:
                raise PageDataError(self.failures[key])
            self.page.wait_for_timeout(100)
        raise PageDataError('单剧详情数据响应超时')


def validate_series(record):
    if (record.get('schema') != 2 or record.get('source') != 'contract_chart' or not isinstance(record.get('id'), str)
            or not record['id'] or not isinstance(record.get('name'), str) or not record['name']):
        raise PageDataError('不认识的单剧历史档案')
    for metric in ('qv', 'dur'):
        for day, value in record.get(metric, {}).items():
            try:
                dt.date.fromisoformat(day)
            except (ValueError, TypeError) as e:
                raise PageDataError('单剧历史日期无效') from e
            if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                    or (metric == 'qv' and type(value) is not int)):
                raise PageDataError('单剧历史包含非法数值')
            segments = record.get('segments', {})
            if not any(label[:10] <= day <= label[11:] and segment.get('status') in ('ok', 'partial')
                       for label, segment in segments.items()):
                raise PageDataError('单剧历史值没有成功查询区间的来源记录')


def upgrade_record(old):
    """Keep old observations' segment timestamps when upgrading their metadata."""
    record = copy.deepcopy(old)
    if not record:
        return record
    for segment in record.get('segments', {}).values():
        if segment.get('status') == 'ok' and segment.get('missing'):
            segment['status'] = 'partial'
    record.setdefault('observedAt', {})
    record.setdefault('observedAtBasis', {})
    for metric in ('qv', 'dur'):
        observed = record['observedAt'].setdefault(metric, {})
        basis = record['observedAtBasis'].setdefault(metric, {})
        for day in record.get(metric, {}):
            if day not in observed:
                stamps = [segment['checked'] for label, segment in record.get('segments', {}).items()
                          if label[:10] <= day <= label[11:] and segment.get('checked')
                          and segment.get('status') in ('ok', 'partial')]
                if stamps:
                    observed[day] = min(stamps)
                    basis[day] = 'archived_segment_timestamp'
    return record


def failure_recent(previous, did, retry_hours, now=None):
    if did not in previous.get('failures', {}):
        return False
    stamp = previous.get('failureChecks', {}).get(did) or previous.get('checked')
    if not stamp:
        return False
    try:
        age = (now or dt.datetime.now(dt.timezone.utc)) - dt.datetime.fromisoformat(stamp)
        return age.total_seconds() < retry_hours * 3600
    except (ValueError, TypeError):
        return False


def collect(page, base, start='2026-03-01', log=print, retry_hours=24):
    root = Path(base) / 'data' / 'v2'
    main = read_json(root / 'latest.json')
    initial = read_json(root / 'periods' / main['periods']['last30'])['rows'][0]['id']
    capture = SeriesCapture(page)
    ui = PageCapture(page)
    try:
        page.goto(f'https://www.tiktokdramacenter.com/series/{initial}/performance/core', wait_until='domcontentloaded')
        page.get_by_role('button', name='Switch drama', exact=True).wait_for(timeout=30000)
        page.get_by_role('button', name='Switch drama', exact=True).click()
        capture.wait(lambda: capture.total is not None and len(capture.catalog) == capture.total, 'catalog')
        if not capture.catalog:
            raise PageDataError('单剧历史目录为空')
        catalog = dict(capture.catalog)
        atomic_json(root / 'series_catalog.json', catalog)
        previous = read_json(root / 'series_latest.json', {})
        saved, errors, failure_checks = 0, {}, {}
        for did, info in catalog.items():
            if failure_recent(previous, did, retry_hours):
                errors[did] = previous['failures'][did]
                failure_checks[did] = previous.get('failureChecks', {}).get(did) or previous['checked']
                continue
            try:
                path = root / 'series' / f'{did}.json'
                old = upgrade_record(read_json(path, {}))
                record = dict(schema=2, source='contract_chart', id=did, name=info['name'],
                              pub=info.get('pub'), episodes=info.get('episodes'),
                              qv=dict(old.get('qv', {})), dur=dict(old.get('dur', {})), segments=dict(old.get('segments', {})),
                              observedAt={m: dict(old.get('observedAt', {}).get(m, {})) for m in ('qv', 'dur')},
                              observedAtBasis={m: dict(old.get('observedAtBasis', {}).get(m, {})) for m in ('qv', 'dur')})
                capture.ranges.pop(did, None)
                capture.failures.pop((did, 'range'), None)
                page.goto(f'https://www.tiktokdramacenter.com/series/{did}/performance/core', wait_until='domcontentloaded')
                page.get_by_role('button', name='Switch drama', exact=True).wait_for(timeout=30000)
                capture.wait(lambda: did in capture.ranges, (did, 'range'))
                bounds = capture.ranges[did]
                record['availability'] = bounds
                record['checked'] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
                if not bounds.get('has_data'):
                    record['audit'] = dict(status='no_data', matchedDays=0)
                    atomic_json(path, record)
                    log(f'单剧历史 {info["name"]}：平台标注暂无数据')
                    continue
                first = max(start, bounds['min_date'])
                last = min(main['latest'], bounds['max_date'])
                record['start'], record['end'] = first, last
                chunks = []
                day = first
                while day <= last:
                    end = min(shift(day, 29), last)
                    chunks.append((day, end))
                    day = shift(end, 1)
                for left, right in reversed(chunks):
                    label = f'{left}_{right}'
                    prior = old.get('segments', {}).get(label, {})
                    if prior.get('status') == 'ok' and prior.get('missing'):
                        prior = dict(prior, status='partial')
                        record['segments'][label] = prior
                    if prior.get('status') == 'ok' and not prior.get('missing') and right < shift(last, -2):
                        continue
                    if prior.get('status') in ('partial', 'unavailable') and prior.get('checked'):
                        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(prior.get('lastAttempted', prior['checked']))
                        if age.total_seconds() < retry_hours * 3600:
                            continue
                    key = (did, left, right, 'qv')
                    try:
                        ui.select_dates(left, right)
                        capture.wait(lambda: key in capture.curves, key)
                        points = parse_curve(capture.curves[key], left, right, 'innerfeed_vv')
                        if not points:
                            raise PageDataError('平台返回空曲线，不按0补齐')
                        # Only replace the dates actually returned, preserving provenance.
                        record['qv'].update(points)
                        record['observedAt']['qv'].update({d: record['checked'] for d in points})
                        record['observedAtBasis']['qv'].update({d: 'response' for d in points})
                        dur_key = (did, left, right, 'dur')
                        if dur_key in capture.curves:
                            try:
                                duration = parse_curve(capture.curves[dur_key], left, right, 'value')
                                record['dur'].update(duration)
                                record['observedAt']['dur'].update({d: record['checked'] for d in duration})
                                record['observedAtBasis']['dur'].update({d: 'response' for d in duration})
                            except PageDataError as e:
                                record.setdefault('durationErrors', {})[label] = str(e)
                        missing = [d for d in date_axis(left, right) if d not in points]
                        record['segments'][label] = dict(status='partial' if missing else 'ok', points=len(points),
                            missing=missing, checked=record['checked'])
                    except PageDataError as e:
                        if prior.get('status') in ('ok', 'partial'):
                            record['segments'][label] = dict(prior, lastAttempted=record['checked'], lastError=str(e))
                        else:
                            record['segments'][label] = dict(status='unavailable', reason=str(e), checked=record['checked'])
                matched, differences = 0, []
                for day, qv in record['qv'].items():
                    direct = read_json(root / 'days' / f'{day}.json')
                    if direct:
                        check_record(direct)
                        if direct['start'] != day or direct['end'] != day:
                            raise PageDataError('用于重合核对的单日档日期不匹配')
                        row = next((r for r in direct['rows'] if r['id'] == did), None)
                        if row is not None:
                            matched += 1
                            if row['qv'] != qv:
                                differences.append(dict(date=day, curve=qv, day=row['qv']))
                record['audit'] = dict(status='conflict' if differences else 'matched' if matched else 'source_only',
                                       matchedDays=matched, differences=differences)
                validate_series(record)
                atomic_json(path, record)
                saved += 1
                log(f'单剧历史 {info["name"]}：{len(record["qv"])} 个播放日值，重合校验 {matched} 天，差异 {len(differences)}')
            except Exception as e:
                # A bad archive or Playwright navigation failure belongs to this title only.
                errors[did] = str(e)
                failure_checks[did] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
                log(f'单剧历史 {info["name"]} 暂不可用：{e}')
        manifest = dict(schema=2, source='contract_chart', requestedStart=start, titles=len(catalog),
                        saved=saved, failures=errors, failureChecks=failure_checks,
                        checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
        atomic_json(root / 'series_latest.json', manifest)
        return manifest
    finally:
        ui.close()
        capture.close()
