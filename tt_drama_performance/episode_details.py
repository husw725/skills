"""Cumulative episode snapshots from the site's normal Core metrics page.

The request has no date filter. The returned range is NOT a data watermark.
Episode counts are never interpreted as a cohort-retention measurement.
"""
import datetime as dt
from pathlib import Path
import re
import time

from analytics_v2 import PageDataError, atomic_json, read_json
from series_details import numeric


def normalize(data):
    start, end = data['start_date'], data['end_date']
    dt.date.fromisoformat(start)
    dt.date.fromisoformat(end)
    if start > end or not isinstance(data.get('episodes'), list) or not data['episodes']:
        raise PageDataError('平台未返回可用分集快照')
    rows, seen = [], set()
    for raw in data['episodes']:
        num = numeric(raw, 'episode_num', count=True)
        qv = numeric(raw, 'innerfeed_vv', count=True)
        highlight = raw.get('is_highlight')
        if (num is None or num > 10000 or qv is None or type(highlight) not in (int, str)
                or highlight not in ('0', '1', 0, 1)):
            raise PageDataError('分集快照缺少集号/播放/片段标识')
        clip = str(highlight) == '1'
        key = (num, clip)
        if key in seen:
            raise PageDataError('分集快照集号重复')
        seen.add(key)
        rows.append(dict(episode=num, highlight=clip, qv=qv))
    return dict(platformRange=dict(start=start, end=end), rows=sorted(rows, key=lambda r: (r['highlight'], r['episode'])))


def validate_record(record, did):
    if (record.get('schema') != 2 or record.get('source') != 'contract_episode_snapshot'
            or record.get('id') != did or not re.fullmatch(r'\d+', did)
            or not isinstance(record.get('name'), str) or not record['name']
            or record.get('queryMode') != 'cumulative_snapshot' or record.get('dataThrough') is not None):
        raise PageDataError('分集存档来源或查询口径异常')
    dt.datetime.fromisoformat(record['lastAttempt'])
    if not record.get('rows'):
        return
    dt.datetime.fromisoformat(record['checked'])
    bounds = record['platformRange']
    dt.date.fromisoformat(bounds['start'])
    dt.date.fromisoformat(bounds['end'])
    if bounds['start'] > bounds['end']:
        raise PageDataError('分集快照范围倒置')
    seen = set()
    for row in record['rows']:
        if (set(row) != {'episode', 'qv', 'highlight'} or type(row['episode']) is not int
                or not 0 <= row['episode'] <= 10000 or type(row['qv']) is not int or row['qv'] < 0
                or type(row['highlight']) is not bool):
            raise PageDataError('分集存档数值异常')
        key = (row['episode'], row['highlight'])
        if key in seen:
            raise PageDataError('分集存档集号重复')
        seen.add(key)


class EpisodeCapture:
    def __init__(self, page):
        self.page, self.values, self.errors = page, {}, {}
        page.on('response', self.response)

    def close(self):
        self.page.remove_listener('response', self.response)

    def response(self, response):
        if not response.url.split('?', 1)[0].endswith('/analytics/contract/episode-views'):
            return
        did = None
        try:
            req = response.request.post_data_json
            did = str(req['contract_id'])
            if set(req) != {'contract_id'}:
                raise PageDataError('分集快照出现未验证的日期/其他筛选')
            obj = response.json()
            if response.status != 200 or obj.get('code') != 0:
                raise PageDataError(f'HTTP {response.status} code {obj.get("code")}')
            self.values[did] = dict(normalize(obj['data']), checked=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
            self.errors.pop(did, None)
        except Exception as e:
            if did is not None:
                self.errors[did] = str(e).splitlines()[0][:180]


def collect(page, base, log=print, retry_hours=24):
    root = Path(base) / 'data' / 'v2'
    latest = read_json(root / 'latest.json')['latest']
    catalog = read_json(root / 'series_catalog.json', {})
    if not catalog or any(not re.fullmatch(r'\d+', did) for did in catalog):
        raise PageDataError('缺少有效的单剧目录')
    capture = EpisodeCapture(page)
    try:
        for did, info in catalog.items():
            path = root / 'episodes' / f'{did}.json'
            old = read_json(path, {})
            now = dt.datetime.now(dt.timezone.utc)
            if old.get('asOf') == latest and old.get('lastAttempt'):
                if (now - dt.datetime.fromisoformat(old['lastAttempt'])).total_seconds() < retry_hours * 3600:
                    continue
            record = dict(old, schema=2, source='contract_episode_snapshot', id=did, name=info['name'],
                          queryMode='cumulative_snapshot', dataThrough=None, asOf=latest,
                          lastAttempt=now.isoformat(timespec='seconds'))
            for attempt in range(3):
                capture.errors.pop(did, None)
                try:
                    page.goto(f'https://www.tiktokdramacenter.com/series/{did}/performance/core',
                              wait_until='domcontentloaded', timeout=15000)
                    deadline = time.monotonic() + 8
                    while did not in capture.values and did not in capture.errors and time.monotonic() < deadline:
                        page.wait_for_timeout(100)
                    if did in capture.values:
                        record.update(capture.values[did])
                        record.pop('lastError', None)
                        break
                    raise PageDataError(capture.errors.get(did, '分集快照响应超时'))
                except Exception as e:
                    record['lastError'] = str(e).splitlines()[0][:180]
            validate_record(record, did)
            if old.get('rows') and old.get('rows') != record.get('rows'):
                stamp = old['checked'].replace(':', '-')
                atomic_json(root / 'episode_revisions' / did / f'{stamp}.json', old)
            atomic_json(path, record)
            log(f'分集累计快照 {info["name"]}：{len(record.get("rows", []))} 个集/片段，' + ('本轮不可用，保留原值' if record.get('lastError') else '已保存'))
    finally:
        capture.close()


def load_episodes(root, errors=None):
    result = {}
    for path in sorted((Path(root) / 'episodes').glob('*.json')):
        try:
            record = read_json(path)
            validate_record(record, path.stem)
            result[path.stem] = record
        except Exception:
            if errors is None:
                raise
            errors.append(path.name)
    return result
