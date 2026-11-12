"""Observed episode pages and single-video second curves; never replay an API."""
import datetime as dt
import math
from pathlib import Path
import re
import time

from analytics_v2 import PageCapture, PageDataError, atomic_json, read_json, shift


class CollectionBudgetExpired(PageDataError):
    pass


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def number(value, *, count=False, rate=False):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise PageDataError('指标不能为布尔值')
    if count and not (type(value) is int or isinstance(value, str) and re.fullmatch(r'\d+', value)):
        raise PageDataError('计数不是非负整数')
    try:
        result = int(value) if count else float(value)
    except (ValueError, TypeError) as exc:
        raise PageDataError('无法解析指标') from exc
    if not math.isfinite(result) or result < 0 or rate and result > 1:
        raise PageDataError('指标数值越界')
    return result


def normalize_page(data, request):
    allowed = {'contract_id', 'start_date', 'end_date', 'after_order_num', 'page_size'}
    if any(value not in (None, '', [], {}) for key, value in request.items() if key not in allowed):
        raise PageDataError('分集请求包含未核准的筛选')
    start, end = request['start_date'], request['end_date']
    for day in (start, end):
        dt.date.fromisoformat(day)
    if start > end or (data.get('start_date'), data.get('end_date')) != (start, end):
        raise PageDataError('分集指标日期不匹配')
    pagination = data['pagination']
    total = number(pagination.get('total'), count=True)
    cursor = number(request.get('after_order_num'), count=True)
    next_cursor = number(pagination.get('next_after_order_num'), count=True)
    more = pagination.get('has_more')
    if total is None or cursor is None or type(more) is not bool or more and (next_cursor is None or next_cursor <= cursor):
        raise PageDataError('分集分页游标异常')
    if not isinstance(data.get('episodes'), list) or more and not data['episodes']:
        raise PageDataError('分集分页不是列表或提前为空')
    rows, seen = [], set()
    for raw in data['episodes']:
        episode = number(raw.get('episode_num'), count=True)
        highlight = raw.get('is_highlight')
        if episode is None or episode > 10000 or type(highlight) not in (str, int) or highlight not in (0, 1, '0', '1'):
            raise PageDataError('分集标识异常')
        key = (episode, str(highlight) == '1')
        if key in seen:
            raise PageDataError('分集标识重复')
        seen.add(key)
        item = str(raw.get('item_id') or '')
        if item and not re.fullmatch(r'\d+', item):
            raise PageDataError('发布视频标识异常')
        versions = raw.get('item_ids') or []
        if not isinstance(versions, list) or any(not re.fullmatch(r'\d+', str(v)) for v in versions):
            raise PageDataError('发布版本列表异常')
        if item and versions and item not in {str(v) for v in versions}:
            raise PageDataError('代表视频不在发布版本中')
        fields = [('qv', 'innerfeed_vv'), ('like', 'like_cnt'), ('fav', 'favourite_cnt'), ('com', 'comment_cnt')]
        rows.append(dict(episode=episode, highlight=key[1], itemId=item or None,
                         itemIds=list(dict.fromkeys(map(str, versions))),
                         versionCount=len(set(map(str, versions))) if raw.get('item_ids') is not None else None,
                         cumulative={k: number(raw.get(f), count=True) for k, f in fields},
                         added={k: number(raw.get('delta_' + f), count=True) for k, f in fields},
                         finishRate=number(raw.get('finish_rate'), rate=True),
                         durationSeconds=number(raw.get('avg_play_duration')),
                         impressions=number(raw.get('impression_pv'), count=True),
                         clicks=number(raw.get('click_pv'), count=True)))
    return dict(start=start, end=end, total=total, cursor=cursor, nextCursor=next_cursor,
                more=more, rows=rows)


def normalize_seconds(data):
    item = str(data.get('item_id') or '')
    if not re.fullmatch(r'\d+', item):
        raise PageDataError('逐秒数据缺少发布视频ID')
    result = dict(itemId=item, queryMode='video_snapshot', dataThrough=None)
    for source, field in [('retention_rate', 'retention'), ('like_rate', 'likes')]:
        raw = data.get(source)
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise PageDataError('逐秒曲线不是列表')
        points, seen = [], set()
        for row in raw:
            second, rate = number(row.get('second'), count=True), number(row.get('rate'), rate=True)
            if second is None or second > 86400 or second in seen:
                raise PageDataError('逐秒时间重复或越界')
            seen.add(second)
            if rate is not None:
                points.append([second, rate])
        result[field] = sorted(points)
    if not result['retention'] and not result['likes']:
        raise PageDataError('平台未返回可用逐秒曲线')
    return result


def normalize_material_catalog(data):
    total, page, size = (number(data.get(k), count=True) for k in ('total', 'page', 'page_size'))
    if total is None or page is None or page < 1 or size is None or size < 1 or not isinstance(data.get('list'), list):
        raise PageDataError('素材目录分页异常')
    rows, seen = [], set()
    for raw in data['list']:
        item = str(raw.get('item_id') or '')
        if not item.isdigit() or item in seen:
            raise PageDataError('素材发布ID重复或缺失')
        seen.add(item)
        account = raw.get('account') or {}
        published = number(raw.get('publish_time'), count=True)
        duration = number(raw.get('duration'))
        rows.append(dict(itemId=item, title=str(raw.get('title') or ''),
                         published=dt.datetime.fromtimestamp(published / 1000, dt.timezone.utc).date().isoformat() if published else None,
                         durationSeconds=duration / 1000 if duration is not None else None,
                         account=dict(name=str(account.get('name') or ''), handle=str(account.get('unique_id') or ''),
                                      region=str(account.get('region') or ''))))
    return dict(total=total, page=page, size=size, rows=rows, checked=stamp())


def normalize_material_stats(data, request):
    start, end = request['start_date'], request['end_date']
    dt.date.fromisoformat(start); dt.date.fromisoformat(end)
    if start > end or (data.get('start_date'), data.get('end_date')) != (start, end):
        raise PageDataError('素材统计日期不匹配')
    if not isinstance(data.get('episodes'), list):
        raise PageDataError('素材统计不是列表')
    expected = set(map(str, request['item_ids']))
    values = {}
    for raw in data['episodes']:
        item = str(raw.get('item_id') or '')
        if item not in expected or item in values:
            raise PageDataError('素材统计ID不匹配或重复')
        values[item] = dict(impressions=number(raw.get('impression_pv'), count=True), clicks=number(raw.get('click_pv'), count=True))
    return dict(start=start, end=end, values=values, checked=stamp())


class Capture:
    def __init__(self, page):
        self.page, self.pages, self.seconds, self.bounds, self.errors = page, {}, {}, {}, {}
        self.material_catalogs, self.material_stats = {}, {}
        self.second_errors = {}
        self.sequence = 0
        page.on('response', self.response)

    def close(self):
        self.page.remove_listener('response', self.response)

    def response(self, response):
        endpoint = response.url.split('?', 1)[0].rsplit('/', 1)[-1]
        if endpoint not in ('episode-page', 'episode-second-stats', 'data-range', 'material-catalog', 'material-stats'):
            return
        key = None
        try:
            request, obj = response.request.post_data_json, response.json()
            did = str(request['contract_id'])
            if endpoint == 'episode-page':
                key = (did, request['start_date'], request['end_date'], int(request['after_order_num']))
            elif endpoint == 'material-catalog':
                key = ('materials', did, int(request.get('page', 1)))
            if response.status != 200 or obj.get('code') != 0:
                raise PageDataError(f'HTTP {response.status} code {obj.get("code")}')
            if endpoint == 'episode-page':
                self.pages[key] = dict(normalize_page(obj['data'], request), checked=stamp())
                self.errors.pop(key, None)
            elif endpoint == 'episode-second-stats':
                if set(request) != {'vid', 'contract_id'}:
                    raise PageDataError('逐秒接口出现未核准筛选')
                self.sequence += 1
                try:
                    value = dict(normalize_seconds(obj['data']), checked=stamp())
                except PageDataError as exc:
                    item = str(obj.get('data', {}).get('item_id') or '')
                    if item.isdigit():
                        self.second_errors[(did, item)] = dict(reason=str(exc), _sequence=self.sequence)
                    return
                value['_sequence'] = self.sequence
                self.seconds[(did, value['itemId'])] = value
                self.second_errors.pop((did, value['itemId']), None)
            elif endpoint == 'material-catalog':
                allowed = {'contract_id', 'page', 'page_size'}
                if any(value not in (None, '', [], {}) for field, value in request.items() if field not in allowed):
                    raise PageDataError('素材目录含未核准的账号筛选')
                value = normalize_material_catalog(obj['data'])
                if value['page'] != int(request.get('page', 1)):
                    raise PageDataError('素材返回页码不匹配')
                self.material_catalogs[(did, value['page'])] = value
            elif endpoint == 'material-stats':
                value = normalize_material_stats(obj['data'], request)
                self.material_stats[(did, tuple(sorted(map(str, request['item_ids']))))] = value
            else:
                self.bounds[did] = obj['data']
        except Exception as exc:
            if key is not None:
                self.errors[key] = (str(exc).splitlines() or [type(exc).__name__])[0][:140]

    def wait(self, predicate, key=None, timeout=12000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if predicate():
                return
            if key in self.errors:
                raise PageDataError(self.errors[key])
            self.page.wait_for_timeout(100)
        raise PageDataError('等待平台分集数据超时')


def validate_record(record, did):
    def stored(value, **kwargs):
        if value is not None and (type(value) not in (int, float) or kwargs.get('count') and type(value) is not int):
            raise PageDataError('存档指标必须为数值或缺失')
        return number(value, **kwargs)
    if (record.get('schema') != 2 or record.get('source') != 'contract_episode_insights'
            or record.get('id') != did or not re.fullmatch(r'\d+', did)
            or not isinstance(record.get('name'), str) or not record['name']):
        raise PageDataError('分集运营档案来源异常')
    if dt.datetime.fromisoformat(record['lastAttempt']).tzinfo is None:
        raise PageDataError('分集运营观测时间缺少时区')
    metrics = record.get('metrics')
    if metrics is not None and not isinstance(metrics, dict):
        raise PageDataError('分集指标表结构异常')
    if metrics is not None:
        if (metrics.get('complete') is not True or not isinstance(metrics.get('rows'), list)
                or stored(metrics.get('total'), count=True) is None or len(metrics['rows']) != metrics['total']):
            raise PageDataError('分集分页未完整验收')
        dt.date.fromisoformat(metrics['start']); dt.date.fromisoformat(metrics['end'])
        if metrics['start'] > metrics['end'] or dt.datetime.fromisoformat(metrics['checked']).tzinfo is None:
            raise PageDataError('分集指标范围异常')
        seen = set()
        for row in metrics['rows']:
            key = (row['episode'], row['highlight'])
            if type(row['episode']) is not int or not 0 <= row['episode'] <= 10000 or type(row['highlight']) is not bool or key in seen:
                raise PageDataError('分集运营标识重复或非法')
            seen.add(key)
            if row['itemId'] is not None and (not isinstance(row['itemId'], str) or not re.fullmatch(r'\d+', row['itemId'])):
                raise PageDataError('分集视频ID异常')
            if not isinstance(row.get('itemIds', []), list) or any(not isinstance(item, str) or not item.isdigit() for item in row.get('itemIds', [])):
                raise PageDataError('分集发布版本ID异常')
            stored(row['versionCount'], count=True)
            for part in ('cumulative', 'added'):
                if set(row[part]) != {'qv', 'like', 'fav', 'com'}:
                    raise PageDataError('分集指标字段异常')
                for value in row[part].values():
                    stored(value, count=True)
            stored(row['finishRate'], rate=True); stored(row['durationSeconds'])
            stored(row['impressions'], count=True); stored(row['clicks'], count=True)
    for item, value in record.get('seconds', {}).items():
        if value.get('itemId') != item or value.get('queryMode') != 'video_snapshot' or value.get('dataThrough') is not None:
            raise PageDataError('逐秒快照来源异常')
        if dt.datetime.fromisoformat(value['checked']).tzinfo is None:
            raise PageDataError('逐秒观测时间缺少时区')
        if type(value.get('episode')) is not int or not 0 <= value['episode'] <= 10000 or type(value.get('highlight')) is not bool:
            raise PageDataError('逐秒存档集号异常')
        for field in ('retention', 'likes'):
            if not isinstance(value[field], list):
                raise PageDataError('逐秒存档曲线不是列表')
            for point in value[field]:
                if (not isinstance(point, list) or len(point) != 2 or type(point[0]) is not int
                        or type(point[1]) not in (int, float)):
                    raise PageDataError('逐秒存档点必须为真实数值，缺秒不存假点')
        normalize_seconds(dict(item_id=item, retention_rate=[dict(second=s, rate=r) for s, r in value['retention']],
                               like_rate=[dict(second=s, rate=r) for s, r in value['likes']]))
    for item, failure in record.get('failures', {}).items():
        if not re.fullmatch(r'\d+', item) or not isinstance(failure.get('reason'), str):
            raise PageDataError('逐秒失败记录异常')
        if dt.datetime.fromisoformat(failure['checked']).tzinfo is None:
            raise PageDataError('逐秒失败时间缺少时区')
    materials = record.get('materials')
    if materials is not None:
        if not isinstance(materials, dict) or materials.get('complete') is not True or not isinstance(materials.get('rows'), list):
            raise PageDataError('素材目录未完整验收')
        if stored(materials['total'], count=True) != len(materials['rows']):
            raise PageDataError('素材目录数量不完整')
        if dt.datetime.fromisoformat(materials['checked']).tzinfo is None:
            raise PageDataError('素材观测时间缺少时区')
        if materials.get('start') is not None:
            dt.date.fromisoformat(materials['start']); dt.date.fromisoformat(materials['end'])
            if materials['start'] > materials['end']:
                raise PageDataError('素材查询日期倒置')
        elif materials.get('end') is not None:
            raise PageDataError('素材查询范围不完整')
        seen = set()
        for row in materials['rows']:
            if not isinstance(row['itemId'], str) or not row['itemId'].isdigit() or row['itemId'] in seen:
                raise PageDataError('素材ID重复或无效')
            seen.add(row['itemId'])
            for field in ('impressions', 'clicks'):
                stored(row[field], count=True)
            stored(row['durationSeconds'])
            if not isinstance(row['title'], str) or not isinstance(row['account'], dict):
                raise PageDataError('素材资料结构异常')
            if row['published'] is not None:
                dt.date.fromisoformat(row['published'])
            if any(not isinstance(row['account'].get(field), str) for field in ('name', 'handle', 'region')):
                raise PageDataError('素材账号资料异常')


def collect_materials(page, capture, did, deadline=None, allow_missing_stats=False):
    close = page.locator('.semi-sidesheet-close:visible')
    if close.count():
        close.first.click(timeout=3000); close.first.wait_for(state='hidden', timeout=4000)
    page.keyboard.press('Escape')
    page.get_by_text('Derivative materials', exact=True).click(timeout=8000)
    capture.wait(lambda: (did, 1) in capture.material_catalogs, ('materials', did, 1))
    first = capture.material_catalogs[(did, 1)]
    catalog, values, seen, scope, stats_partial = [], {}, set(), None, False
    pages = max(1, math.ceil(first['total'] / first['size']))
    for num in range(1, pages + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise CollectionBudgetExpired('本轮素材采集预算已用完，后续继续')
        if num > 1:
            page.locator('#semiTabPanelmaterials .semi-page-item').filter(has_text=re.compile(f'^{num}$')).click(timeout=5000)
        capture.wait(lambda: (did, num) in capture.material_catalogs, ('materials', did, num))
        current = capture.material_catalogs[(did, num)]
        if current['total'] != first['total']:
            raise PageDataError('素材目录翻页时总数改变')
        ids = tuple(sorted(row['itemId'] for row in current['rows']))
        if ids:
            try:
                capture.wait(lambda: (did, ids) in capture.material_stats)
            except PageDataError:
                if not allow_missing_stats:
                    raise
                stats_partial = True
            if (did, ids) in capture.material_stats:
                stats = capture.material_stats[(did, ids)]
                if scope is not None and scope != (stats['start'], stats['end']):
                    raise PageDataError('素材翻页统计日期改变')
                scope = (stats['start'], stats['end'])
                values.update(stats['values'])
        for row in current['rows']:
            if row['itemId'] in seen:
                raise PageDataError('素材分页ID重复')
            seen.add(row['itemId']); catalog.append(row)
    if len(catalog) != first['total']:
        raise PageDataError('素材目录未采齐')
    rows = [dict(row, **values.get(row['itemId'], dict(impressions=None, clicks=None))) for row in catalog]
    return dict(complete=True, total=first['total'], rows=rows, checked=stamp(),
                start=scope[0] if scope else None, end=scope[1] if scope else None,
                statsRows=len(values), statsPartial=stats_partial or len(values) < first['total'])


def collect(page, base, log=print, retry_hours=24, budget_seconds=1200, only_ids=None, seconds_per_title=10):
    if not math.isfinite(budget_seconds) or budget_seconds <= 0 or not 1 <= seconds_per_title <= 10000:
        raise ValueError('分集采集预算和逐剧批量必须为正数')
    root = Path(base) / 'data/v2'
    latest = read_json(root / 'latest.json')['latest']
    catalog = read_json(root / 'series_catalog.json')
    capture, ui = Capture(page), PageCapture(page)
    deadline, results = time.monotonic() + budget_seconds, {}
    try:
        def publish_order(entry):
            try:
                return int(entry[1].get('pub') or 0)
            except (TypeError, ValueError):
                return 0
        ordered = sorted(catalog.items(), key=publish_order, reverse=True)
        for did, info in ordered:
            if only_ids is not None and did not in only_ids:
                continue
            if time.monotonic() >= deadline:
                break
            path = root / 'episode_insights' / f'{did}.json'
            metrics_collected = False
            try:
                old = read_json(path, {})
                if old:
                    validate_record(old, did)
                upgraded = old.get('collectorVersion', 0) < 3
                if not upgraded and old.get('asOf') == latest and not old.get('pending') and old.get('lastAttempt'):
                    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(old['lastAttempt'])).total_seconds()
                    if 0 <= age < retry_hours * 3600:
                        continue
                record = dict(old, schema=2, source='contract_episode_insights', id=did, name=info['name'],
                              asOf=latest, lastAttempt=stamp(), seconds=dict(old.get('seconds', {})),
                              failures=dict(old.get('failures', {})), pending=True, collectorVersion=3)
                def preserve_old():
                    if not old.get('metrics') and not old.get('seconds'):
                        return
                    revision = root / 'episode_insights_revisions' / did / (old['lastAttempt'].replace(':', '-') + '.json')
                    if not revision.exists():
                        atomic_json(revision, old)
                if upgraded and record['failures']:
                    preserve_old()
                    record['failures'] = {}
                page.goto(f'https://www.tiktokdramacenter.com/series/{did}/performance/core', wait_until='domcontentloaded', timeout=20000)
                capture.wait(lambda: any(key[0] == did and key[3] == 0 for key in capture.pages), timeout=15000)
                bounds = capture.bounds.get(did, {})
                end = min(latest, bounds.get('max_date', latest))
                start = max(shift(end, -29), bounds.get('min_date', shift(end, -29)))
                if info.get('pub'):
                    published = dt.datetime.fromtimestamp(int(info['pub']), dt.timezone.utc).date().isoformat()
                    start = max(start, published)
                if start > end:
                    raise PageDataError('发布日尚未进入平台可查日期范围')
                record['requested'] = dict(start=start, end=end)
                key = (did, start, end, 0)
                if key not in capture.pages:
                    ui.select_dates(start, end)
                capture.wait(lambda: key in capture.pages, key)
                pages, seen, cursor, rows, total = [], set(), 0, [], None
                while True:
                    if time.monotonic() >= deadline:
                        raise CollectionBudgetExpired('本轮分集采集预算已用完，后续继续')
                    key = (did, start, end, cursor)
                    capture.wait(lambda: key in capture.pages, key)
                    value = capture.pages[key]
                    if total is not None and total != value['total']:
                        raise PageDataError('分集总数在翻页中改变')
                    total = value['total']; pages.append(cursor)
                    for row in value['rows']:
                        identity = (row['episode'], row['highlight'])
                        if identity in seen:
                            raise PageDataError('分集分页重复，拒绝合并')
                        seen.add(identity); rows.append(row)
                    if not value['more']:
                        break
                    cursor = value['nextCursor']
                    page.wait_for_timeout(200)
                    scroll = page.locator('.semi-table-body:visible').last
                    scroll.evaluate('(el)=>{el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll",{bubbles:true}));}', timeout=5000)
                if len(rows) != total:
                    raise PageDataError('分集分页条数不完整')
                metrics = dict(start=start, end=end, checked=stamp(), total=total, rows=rows, complete=True, cursors=pages)
                if old.get('metrics') and any(old['metrics'].get(k) != metrics[k] for k in ('start', 'end', 'rows', 'total')):
                    preserve_old()
                record['metrics'] = metrics
                metrics_collected = True
                atomic_json(path, record)
                owners = {}
                for row in rows:
                    if not row['highlight'] and row['episode'] > 0:
                        for video in set(row.get('itemIds', [])) | ({row['itemId']} if row['itemId'] else set()):
                            owners.setdefault(video, set()).add(row['episode'])
                def video_ids(row):
                    return {item for item in set(row.get('itemIds', [])) | ({row['itemId']} if row['itemId'] else set())
                            if len(owners.get(item, ())) <= 1}
                def observed(values, row):
                    matches = [v for item, v in values.items() if item in video_ids(row)
                               and v.get('episode', row['episode']) == row['episode']]
                    return max(matches, key=lambda v: v['checked']) if matches else None
                def close_drawer():
                    close = page.locator('.semi-sidesheet-close:visible')
                    if close.count():
                        close.first.click(timeout=3000)
                        close.first.wait_for(state='hidden', timeout=4000)
                attempts = 0
                for row in rows:
                    item = row['itemId']
                    if row['highlight'] or row['episode'] <= 0 or not item:
                        continue
                    if time.monotonic() >= deadline:
                        break
                    previous = observed(record['seconds'], row)
                    if previous and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(previous['checked'])).total_seconds() < retry_hours * 3600:
                        continue
                    failure = record['failures'].get(item)
                    if not upgraded and failure and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(failure['checked'])).total_seconds() < retry_hours * 3600:
                        continue
                    if attempts >= seconds_per_title:
                        break
                    attempts += 1
                    try:
                        baseline = capture.sequence
                        close = page.locator('.semi-sidesheet-close:visible')
                        if close.count():
                            page.get_by_text('Switch episode', exact=True).click(timeout=4000)
                            option = page.get_by_role('option', name=f'Episode {row["episode"]}', exact=True)
                            if option.count():
                                option.click(timeout=4000)
                            else:
                                close_drawer()
                        if not page.locator('.semi-sidesheet-close:visible').count():
                            table_row = page.locator(f'tr[data-row-key="analytics:{did}:{row["episode"]}"]')
                            table_row.get_by_role('button', name='Episode data', exact=True).click(timeout=8000)
                        def current_video():
                            return observed({key[1]: value for key, value in capture.seconds.items()
                                             if key[0] == did and value['_sequence'] > baseline}, row)
                        def current_ready():
                            if current_video() is not None:
                                return True
                            for key, error in getattr(capture, 'second_errors', {}).items():
                                if key[0] == did and key[1] in video_ids(row) and error['_sequence'] > baseline:
                                    raise PageDataError(error['reason'])
                            return False
                        capture.wait(current_ready, timeout=8000)
                        observed_video = current_video()
                        value = {key: observed_video[key] for key in ('itemId', 'queryMode', 'dataThrough', 'retention', 'likes', 'checked')}
                        value.update(episode=row['episode'], highlight=False)
                        if previous and any(previous.get(k) != value[k] for k in ('retention', 'likes')):
                            preserve_old()
                        record['seconds'][value['itemId']] = value
                        record['failures'].pop(item, None)
                    except Exception as exc:
                        record['failures'][item] = dict(checked=stamp(), reason=(str(exc).splitlines() or [type(exc).__name__])[0][:140])
                        close_drawer()
                    atomic_json(path, record)
                    if attempts % 5 == 0:
                        log(f'逐秒进度 {info["name"]}：本轮尝试{attempts}，已存{len(record["seconds"])}份视频快照')
                close_drawer()
                remaining = [r for r in rows if r['itemId'] and r['episode'] > 0 and not r['highlight']
                             and not observed(record['seconds'], r) and r['itemId'] not in record['failures']]
                record['pending'] = bool(remaining)
                record.pop('lastError', None)
                validate_record(record, did)
                atomic_json(path, record)
                results[did] = dict(rows=len(rows), curves=len(record['seconds']), failures=len(record['failures']), pending=record['pending'])
                log(f'分集运营 {info["name"]}：{len(rows)}集/片段，{len(record["seconds"])}份逐秒视频快照，待继续={record["pending"]}')
            except Exception as exc:
                # Keep the last validated observation while recording this failed attempt.
                if 'record' in locals() and record.get('id') == did:
                    record['lastError'] = (str(exc).splitlines() or [type(exc).__name__])[0][:160]
                    record['pending'] = metrics_collected or isinstance(exc, CollectionBudgetExpired)
                    validate_record(record, did)
                    atomic_json(path, record)
                results[did] = dict(error=type(exc).__name__)
                log(f'分集运营 {did}：{type(exc).__name__}，保留已验收值并继续')
            if 'record' in locals() and record.get('id') == did:
                if time.monotonic() >= deadline:
                    record['pending'] = True
                else:
                    try:
                        old_materials = old.get('materials') or {}
                        old_values = {r['itemId'] for r in old_materials.get('rows', [])
                                      if r['impressions'] is not None or r['clicks'] is not None}
                        materials = collect_materials(page, capture, did, deadline, allow_missing_stats=not old_values)
                        new_values = {r['itemId'] for r in materials['rows'] if r['impressions'] is not None or r['clicks'] is not None}
                        same_scope = (old_materials.get('start'), old_materials.get('end')) == (materials['start'], materials['end'])
                        if old_values and (not new_values or same_scope and not old_values <= new_values):
                            raise PageDataError('素材本轮统计缺失，保留上次同源快照')
                        if old.get('materials') and old['materials']['rows'] != materials['rows']:
                            preserve_old()
                        record['materials'] = materials
                        record.pop('materialError', None)
                        log(f'素材表现 {info["name"]}：{materials["total"]}条目录，{materials["statsRows"]}条统计')
                    except Exception as exc:
                        record['materialError'] = dict(checked=stamp(), reason=(str(exc).splitlines() or [type(exc).__name__])[0][:140])
                        if isinstance(exc, CollectionBudgetExpired):
                            record['pending'] = True
                validate_record(record, did)
                atomic_json(path, record)
        atomic_json(root / 'episode_insights_latest.json', dict(schema=2, checked=stamp(), results=results))
        return results
    finally:
        ui.close(); capture.close()


def load_records(root, errors=None):
    result = {}
    for path in sorted((Path(root) / 'episode_insights').glob('*.json')):
        try:
            value = read_json(path); validate_record(value, path.stem); result[path.stem] = value
        except Exception:
            if errors is None:
                raise
            errors.append(path.name)
    return result
