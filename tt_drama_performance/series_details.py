"""Audience and traffic snapshots observed from normal single-title UI actions.

These are separate platform measurements, not reconciled institution-day data.
Only a whitelist of aggregate fields is persisted; no signed URLs or headers.
"""
import datetime as dt
import math
from pathlib import Path
import re
import time

from analytics_v2 import PageCapture, PageDataError, atomic_json, read_json, shift
from series_history import SeriesCapture

ENDPOINTS = ('audience-stats', 'traffic-stats', 'accounts', 'traffic-added')


def numeric(row, field, count=False):
    value = row.get(field)
    if value is None:
        return None
    if type(value) is bool:
        raise PageDataError(f'{field} 不是数值')
    if count and not (type(value) is int or isinstance(value, str) and re.fullmatch(r'\d+', value)):
        raise PageDataError(f'{field} 不是整数')
    try:
        result = int(value) if count else float(value)
    except (ValueError, TypeError, OverflowError) as e:
        raise PageDataError(f'{field} 无法解析') from e
    if not math.isfinite(result) or result < 0 or (not count and result > 100):
        raise PageDataError(f'{field} 数值越界')
    return result


def distribution(rows):
    if all(v is None for v in rows.values()):
        return None
    if (any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100
            for v in rows.values()) or abs(sum(rows.values()) - 100) > .15):
        raise PageDataError('画像分布缺失或合计不为100%')
    return rows


def normalize(endpoint, data, start, end):
    if (data.get('start_date'), data.get('end_date')) != (start, end):
        raise PageDataError('单剧画像/流量返回日期范围不匹配')
    if endpoint == 'audience-stats':
        rows = data.get('audience', [])
        if not rows:
            raise PageDataError('平台未返回观众画像，不按0填充')
        if len(rows) != 1:
            raise PageDataError('观众画像条数异常')
        row = rows[0]
        gender = distribution({k: numeric(row, f'{k}_pct') for k in ('male', 'female', 'gender_unknown')})
        age = {k: numeric(row, f'{k}_pct') for k in ('l3', 'l4', 'l5')}
        other, unknown = numeric(row, 'other_pct'), numeric(row, 'age_unknown_pct')
        age['unknown'] = other + unknown if other is not None and unknown is not None else None
        age = distribution(age)
        if gender is None and age is None:
            raise PageDataError('平台未提供可用的性别或年龄统计')
        return dict(gender=gender, age=age)
    field = 'channels' if endpoint == 'traffic-stats' else 'accounts'
    rows = data.get(field)
    if not isinstance(rows, list) or not rows:
        raise PageDataError(f'平台未返回{field}，不按0填充')
    result, seen = [], set()
    for row in rows:
        cid = str(row.get('collection_id') or '')
        if endpoint == 'traffic-stats':
            channel = row.get('channel_key')
            if not isinstance(channel, str) or not channel:
                raise PageDataError('流量渠道缺少标识')
            key = (cid, channel)
            result.append(dict(collectionId=cid or None, key=channel, pct=numeric(row, 'share_pct')))
            if result[-1]['pct'] is None:
                raise PageDataError('渠道占比缺失')
        else:
            if not re.fullmatch(r'\d+', cid):
                raise PageDataError('发布账号版本缺少稳定ID')
            key = cid
            if endpoint == 'accounts':
                result.append(dict(collectionId=cid, name=str(row.get('name') or ''),
                                   handle=str(row.get('unique_id') or ''), region=str(row.get('region') or '')))
            else:
                result.append(dict(collectionId=cid, **{k: numeric(row, f'delta_{f}', count=True)
                    for k, f in [('qv', 'innerfeed_vv'), ('like', 'like_cnt'), ('com', 'comment_cnt'), ('fav', 'favourite_cnt')]}))
        if key in seen:
            raise PageDataError('单剧流量明细ID/渠道重复')
        seen.add(key)
    if endpoint == 'traffic-stats':
        scopes = {}
        for r in result:
            scopes.setdefault(r['collectionId'], []).append(r['pct'])
        if any(abs(sum(pcts) - 100) > .15 for pcts in scopes.values()):
            raise PageDataError('流量渠道占比合计不为100%')
    return result


class DetailCapture:
    def __init__(self, page):
        self.page, self.values, self.errors = page, {}, {}
        page.on('response', self.response)

    def close(self):
        self.page.remove_listener('response', self.response)

    def response(self, response):
        path = response.url.split('?', 1)[0]
        endpoint = path.rsplit('/', 1)[-1]
        if '/api/content-partner/analytics/contract/' not in path or endpoint not in ENDPOINTS:
            return
        key = None
        try:
            req = response.request.post_data_json
            key = (str(req['contract_id']), req['start_date'], req['end_date'], endpoint)
            if any(v not in (None, '', [], {}) for k, v in req.items()
                   if k not in ('contract_id', 'start_date', 'end_date')):
                raise PageDataError('单剧请求含额外筛选')
            obj = response.json()
            if response.status != 200 or obj.get('code') != 0:
                raise PageDataError(f'HTTP {response.status} code {obj.get("code")}')
            value = normalize(endpoint, obj['data'], key[1], key[2])
            self.values[key] = dict(start=key[1], end=key[2],
                checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), data=value)
            self.errors.pop(key, None)
        except Exception as e:
            if key is not None:
                self.errors[key] = str(e).splitlines()[0][:180]

    def wait(self, keys, timeout=12000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if all(k in self.values or k in self.errors for k in keys):
                return
            self.page.wait_for_timeout(100)


def available_observation(values, did, endpoint, attempted, latest):
    choices = [v for k, v in values.items() if k[0] == did and k[-1] == endpoint
               and v['end'] <= latest and v['checked'] >= attempted]
    return max(choices, key=lambda v: (v['end'], v['checked'])) if choices else None


def validate_record(obj, did):
    if (obj.get('schema') != 2 or obj.get('source') != 'contract_detail' or obj.get('id') != did
            or not re.fullmatch(r'\d+', did) or not isinstance(obj.get('name'), str) or not obj['name']):
        raise PageDataError('单剧画像存档格式异常')
    dt.date.fromisoformat(obj['asOf'])
    if dt.datetime.fromisoformat(obj['lastAttempt']).tzinfo is None:
        raise PageDataError('详情采集时间缺少时区')
    for endpoint, section in obj.get('sections', {}).items():
        if endpoint not in ENDPOINTS:
            raise PageDataError('不认识的单剧详情分区')
        dt.date.fromisoformat(section['start'])
        dt.date.fromisoformat(section['end'])
        dt.datetime.fromisoformat(section['checked'])
        if section['start'] > section['end']:
            raise PageDataError('单剧详情日期倒置')
        data = section['data']
        if endpoint == 'audience-stats':
            if data.get('gender') is None and data.get('age') is None:
                raise PageDataError('画像分区没有可用统计')
            for field, keys in [('gender', {'male', 'female', 'gender_unknown'}),
                                ('age', {'l3', 'l4', 'l5', 'unknown'})]:
                if data[field] is not None:
                    if set(data[field]) != keys:
                        raise PageDataError('画像类别异常')
                    distribution(data[field])
            continue
        if not isinstance(data, list) or not data:
            raise PageDataError('详情明细为空或格式异常')
        seen, scopes = set(), {}
        for row in data:
            cid = row['collectionId']
            if cid is not None and not re.fullmatch(r'\d+', cid):
                raise PageDataError('发布版本ID异常')
            key = (cid, row['key']) if endpoint == 'traffic-stats' else cid
            if key in seen or (not cid and endpoint != 'traffic-stats'):
                raise PageDataError('详情明细ID/渠道重复或缺失')
            seen.add(key)
            if endpoint == 'traffic-stats':
                if type(row['pct']) not in (int, float):
                    raise PageDataError('渠道比例存档不是数值')
                value = numeric(row, 'pct')
                if value is None:
                    raise PageDataError('渠道比例缺失')
                scopes.setdefault(cid, []).append(value)
            elif endpoint == 'traffic-added':
                for field in ('qv', 'like', 'fav', 'com'):
                    if row[field] is not None and type(row[field]) is not int:
                        raise PageDataError('账号增量存档不是整数')
                    numeric(row, field, count=True)
            else:
                if set(row) != {'collectionId', 'name', 'handle', 'region'}:
                    raise PageDataError('账号元数据含未允许字段')
                if any(not isinstance(row[k], str) for k in ('name', 'handle', 'region')):
                    raise PageDataError('账号元数据格式异常')
        if any(abs(sum(values) - 100) > .15 for values in scopes.values()):
            raise PageDataError('渠道占比合计不为100%')


def load_details(root, errors=None):
    """Reject invalid snapshots; report callers may explicitly omit and flag them."""
    result = []
    for path in sorted((Path(root) / 'details').glob('*.json')):
        try:
            obj = read_json(path)
            validate_record(obj, path.stem)
            result.append(obj)
        except Exception:
            if errors is None:
                raise
            errors.append(path.name)
    return result


def collect(page, base, log=print, retry_hours=24, refresh_hours=24):
    root = Path(base) / 'data' / 'v2'
    main = read_json(root / 'latest.json')
    initial = read_json(root / 'periods' / main['periods']['last30'])['rows'][0]['id']
    series, capture, ui = SeriesCapture(page), DetailCapture(page), PageCapture(page)
    try:
        page.goto(f'https://www.tiktokdramacenter.com/series/{initial}/performance/core', wait_until='domcontentloaded')
        page.get_by_role('button', name='Switch drama', exact=True).click(timeout=30000)
        series.wait(lambda: series.total is not None and len(series.catalog) == series.total, 'catalog')
        catalog = dict(series.catalog)
        if not catalog:
            raise PageDataError('单剧详情目录为空')
        atomic_json(root / 'series_catalog.json', catalog)
        for did, info in catalog.items():
            path = root / 'details' / f'{did}.json'
            old = read_json(path, {})
            now = dt.datetime.now(dt.timezone.utc)
            if old.get('asOf') == main['latest'] and old.get('lastAttempt'):
                cooldown = retry_hours if old.get('failures') else refresh_hours
                if (now - dt.datetime.fromisoformat(old['lastAttempt'])).total_seconds() < cooldown * 3600:
                    continue
            record = dict(schema=2, source='contract_detail', id=did, name=info['name'],
                          asOf=main['latest'], lastAttempt=now.isoformat(timespec='seconds'),
                          sections=dict(old.get('sections', {})), failures={}, fallbacks={})
            try:
                for attempt in range(3):
                    try:
                        series.ranges.pop(did, None)
                        series.failures.pop((did, 'range'), None)
                        page.goto(f'https://www.tiktokdramacenter.com/series/{did}/performance/audience', wait_until='domcontentloaded')
                        page.get_by_text('Audience', exact=True).wait_for(timeout=30000)
                        try:
                            series.wait(lambda: did in series.ranges or (did, 'range') in series.failures,
                                        (did, 'range'), timeout=8000)
                        except PageDataError:
                            pass  # Availability is optional, never a gate for other tabs.
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                bounds = series.ranges.get(did)
                # Core-chart availability is not evidence about other tabs.
                # Its failure must never prevent an Audience/Traffic attempt.
                if not bounds or not bounds.get('has_data'):
                    bounds = read_json(root / 'series' / f'{did}.json', {}).get('availability')
                end = min(main['latest'], bounds['max_date']) if bounds and bounds.get('has_data') else main['latest']
                start = max(shift(end, -29), bounds['min_date']) if bounds and bounds.get('has_data') else shift(end, -29)
                if start > end:
                    raise PageDataError('平台数据范围与报告截止日无重合')
                record['requested'] = dict(start=start, end=end)
                for tab, endpoints in [('Audience', ('audience-stats',)),
                                       ('Traffic', ('traffic-stats', 'accounts', 'traffic-added'))]:
                    keys = [(did, start, end, e) for e in endpoints]
                    for attempt in range(3):
                        pending = [k for k in keys if k not in capture.values]
                        if not pending:
                            break
                        try:
                            if attempt:
                                page.reload(wait_until='domcontentloaded')
                            page.get_by_text(tab, exact=True).click(timeout=15000)
                            ui.select_dates(start, end, timeout=8000)
                            capture.wait(pending)
                        except Exception as e:
                            for key in pending:
                                capture.errors[key] = str(e).splitlines()[0][:180]
                        # Reload produces new normal page requests on the next attempt.
                        for key in pending:
                            if key not in capture.values:
                                if attempt < 2:
                                    capture.errors.pop(key, None)
                    for key in keys:
                        if key in capture.values:
                            record['sections'][key[-1]] = capture.values[key]
                        else:
                            record['failures'][key[-1]] = capture.errors.get(key, '页面未返回匹配范围的数据')
                            # A title may lag behind the institution's date limit.
                            # Keep a successful normal-page observation of its own
                            # actual scope, rather than discarding it or relabeling it.
                            alternative = available_observation(capture.values, did, key[-1],
                                                                record['lastAttempt'], main['latest'])
                            if alternative:
                                record['sections'][key[-1]] = alternative
                                record['fallbacks'][key[-1]] = 'requested_range_unavailable'
            except Exception as e:
                record['failures']['page'] = str(e).splitlines()[0][:180]
            validate_record(record, did)
            if old.get('sections') and old['sections'] != record['sections']:
                stamp = old.get('lastAttempt', now.isoformat(timespec='seconds')).replace(':', '-')
                atomic_json(root / 'details_revisions' / did / f'{stamp}.json', old)
            atomic_json(path, record)
            log(f'单剧画像/流量 {info["name"]}：{len(record["sections"])}/4 分区，当前失败 {len(record["failures"])}')
        snapshots = load_details(root)
        manifest = dict(schema=2, source='contract_detail', titles=len(catalog),
            withAudience=sum('audience-stats' in r.get('sections', {}) for r in snapshots),
            withTraffic=sum('traffic-stats' in r.get('sections', {}) for r in snapshots),
            checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
        atomic_json(root / 'details_latest.json', manifest)
        return manifest
    finally:
        series.close()
        capture.close()
        ui.close()
