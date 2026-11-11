"""Report explicit page intervals without mixing legacy cumulative deltas."""
from collections import defaultdict
import datetime as dt
import html
from pathlib import Path

from analytics_v2 import check_record, date_axis, error_kind, read_json, shift


def aggregate(rows, groups):
    members = {str(m): name for name, ids in groups.items() if not name.startswith('_') for m in ids}
    merged = {}
    for row in rows:
        key = members.get(row['id']) or members.get(row['name']) or row['id']
        r = dict(row)
        r['groupName'] = key if key != row['id'] else row['name']
        e = merged.setdefault(key, dict(id=key, name=r['groupName'], qv=0, like=0, com=0, fav=0,
                                        members=[], memberIds=[], launch=None, _durw=0, _durq=0))
        for k in ('qv', 'like', 'com', 'fav'):
            e[k] += r[k]
        if r.get('launch') and (not e['launch'] or r['launch'] > e['launch']):
            e['launch'] = r['launch']
        if r.get('dur') is not None:
            e['_durw'] += r['dur'] * r['qv']
            e['_durq'] += r['qv']
        e['members'].append(r)
        e['memberIds'].append(r['id'])
    for e in merged.values():
        e['dur'] = round(e.pop('_durw') / e['_durq'], 1) if e['_durq'] else None
        del e['_durq']
        e['engage'] = (e['like'] + e['com'] + e['fav']) / e['qv'] if e['qv'] else None
        e['fav1k'] = e['fav'] * 1000 / e['qv'] if e['qv'] else None
        if len(e['members']) == 1:
            e['episodes'] = e['members'][0].get('episodes')
            e['members'] = []
    return sorted(merged.values(), key=lambda r: -r['qv'])


def account_comparison(detail, periods, direct):
    section = detail.get('sections', {}).get('traffic-added')
    if not section:
        return dict(status='unavailable')
    start, end, did = section['start'], section['end'], detail['id']
    rows = None
    for record in periods.values():
        if (record['start'], record['end']) == (start, end):
            row = next((r for r in record['rows'] if r['id'] == did), None)
            if row is not None:
                rows = [row]
                break
    if rows is None:
        rows = []
        for day in date_axis(start, end):
            row = next((r for r in direct.get(day, {}).get('rows', []) if r['id'] == did), None)
            if row is None:
                return dict(status='unavailable')
            rows.append(row)
    fields = ('qv', 'like', 'fav', 'com')
    if any(r.get(k) is None for r in section['data'] for k in fields):
        return dict(status='unavailable')
    platform = {k: sum(r[k] for r in section['data']) for k in fields}
    primary = {k: sum(r[k] for r in rows) for k in fields}
    return dict(status='matched' if platform == primary else 'different', platform=platform, primary=primary)


def build_payload(base):
    from generate_report import fmt, fmt_en, pct, safe_div
    base = Path(base)
    root = base / 'data' / 'v2'
    manifest = read_json(root / 'latest.json')
    latest = manifest['latest']
    groups = read_json(base / 'groups.json', {})
    records = {k: read_json(root / 'periods' / name) for k, name in manifest['periods'].items()}
    for record in records.values():
        check_record(record)
        if record['audit']['status'] != 'ok' or record['asOf'] != latest:
            raise ValueError('新版报告只能使用同一截止日且通过验收的区间')
    institution = read_json(root / 'institution_daily.json', {})
    history = read_json(base / 'data' / 'daily_history.json', {})
    keys = ('vv', 'qv', 'finish', 'playDur', 'likes', 'comments', 'favs', 'shares')
    # Primary analyses exclusively use v2 measurements. Legacy values are exposed
    # in a separate archive, never spliced into the new daily growth charts.
    daily_map = {}
    for day, qv in institution.items():
        if day <= latest:
            daily_map[day] = dict(date=day, source='page_v2', **{k: None for k in keys})
            daily_map[day]['qv'] = qv
    direct = {}
    for path in sorted((root / 'days').glob('*.json')):
        day = path.stem
        if day > latest:
            continue
        record = read_json(path)
        check_record(record)
        if record['audit']['status'] != 'ok':
            continue
        # A stored day can be revised by a newer institution trend; don't display
        # a stale drama day as reconciled until it has been recollected.
        if institution.get(day) != record['audit']['trendQv']:
            continue
        direct[day] = record
        if day in daily_map:
            for out, field in (('likes', 'like'), ('comments', 'com'), ('favs', 'fav')):
                daily_map[day][out] = sum(r[field] for r in record['rows'])
    if not direct or latest not in direct:
        raise ValueError('缺少最新数据日的已验收剧目明细')
    catalog = {}
    for _, record in sorted(direct.items()):
        for r in record['rows']:
            catalog[r['id']] = {k: r.get(k) for k in ('name', 'launch', 'episodes')}
    member_groups = {str(m): name for name, ids in groups.items() if not name.startswith('_') for m in ids}
    group_map = {did: member_groups.get(did) or member_groups.get(row['name']) or did for did, row in catalog.items()}
    daily = [daily_map.get(day, dict(date=day, source='missing', **{k: None for k in keys}))
             for day in date_axis(min(daily_map), latest)]
    # Current cumulative numbers are taken from the PAGE across all four ranges,
    # never from Excel or from differences between old and new schemas.
    cumulative = {}
    cumulative_scope = 0
    for record in sorted(records.values(), key=lambda r: r['checked']):
        if record.get('contractAsOf', record['asOf']) != latest:
            continue
        cumulative_scope = max(cumulative_scope, (dt.date.fromisoformat(latest)-dt.date.fromisoformat(record['start'])).days+1)
        for r in record['rows']:
            cumulative[r['id']] = dict(id=r['id'], name=r['name'], launch=r['launch'],
                                       episodes=r.get('episodes'), duration=r.get('duration'), **r['cumulative'])
    dramas = aggregate(cumulative.values(), groups)
    for drama in dramas:
        for member in drama.get('members', []):
            member['engage'] = safe_div(member['like'] + member['com'] + member['fav'], member['qv'])
            member['fav1k'] = safe_div(member['fav'] * 1000, member['qv'])

    periods, wow_periods = [], []
    for n in (7, 30):
        current, previous = records[f'last{n}'], records.get(f'previous{n}')
        now_rows = aggregate(current['rows'], groups)
        old_rows = aggregate(previous['rows'], groups) if previous else []
        old_by_id = {r['id']: r for r in old_rows}
        total = current['audit']['trendQv']
        for row in now_rows:
            prev = old_by_id.get(row['id'])
            comparable = prev is not None and set(row['memberIds']) == set(prev['memberIds'])
            row['comparisonCoverage'] = comparable
            row['previousQv'] = prev['qv'] if comparable else None
            row['change'] = safe_div(row['qv'] - prev['qv'], prev['qv']) if comparable else None
            row['share'] = safe_div(row['qv'], total)
            row['new14'] = bool(row['launch'] and shift(latest, -13) <= row['launch'] <= latest)
            row['interactions1k'] = (row['like'] + row['com'] + row['fav']) * 1000 / row['qv'] if row['qv'] else None
        periods.append(dict(n=n, start=current['start'], end=current['end'], rows=now_rows,
                            total=total, previous=previous['audit']['trendQv'] if previous else None,
                            label=f'近{n}日', label_en=f'Last {n}d'))
        if previous is None:
            continue
        rows = []
        for key, label, en in (('qv', '有效播放', 'Effective views'), ('like', '点赞', 'Likes'),
                               ('fav', '收藏', 'Favorites'), ('com', '评论', 'Comments')):
            a = sum(r[key] for r in current['rows'])
            b = sum(r[key] for r in previous['rows'])
            rows.append(dict(metric=label, metric_en=en, w1=fmt(a), w1_en=fmt_en(a),
                             w0=fmt(b), w0_en=fmt_en(b), chg=safe_div(a-b, b)))
        wow_periods.append(dict(n=n, label=f'近{n}日', label_en=f'Last {n}d', rows=rows))

    movers, trends = [], defaultdict(list)
    gaps = []
    for day, record in sorted(direct.items()):
        ranked = aggregate(record['rows'], groups)
        for r in ranked:
            trends[r['id']].append(dict(d=day, qv=r['qv'], days=1, source='page_v2'))
        displayed = ranked[:10] + [r for r in ranked[10:] if r['launch'] and shift(day, -13) <= r['launch'] <= day]
        movers.append(dict(frm=shift(day, -1), to=day, days=1, source='page_v2',
                           rows=[dict(name=r['name'], d_qv=r['qv'], d_like=r['like'], d_fav=r['fav'],
                                      qv0=None, qv1=None, launch=r['launch'],
                                      new7=bool(r['launch'] and shift(day, -13) <= r['launch'] <= day)) for r in displayed],
                           totQv=record['audit']['trendQv']))

    p7, p30 = periods
    latest_qv = institution[latest]
    prev_qv = institution.get(shift(latest, -1))
    top3 = safe_div(sum(r['qv'] for r in p7['rows'][:3]), p7['total'])
    kpis = []
    for label, en, value, change in (
        ('最新日有效播放', 'Latest daily effective views', latest_qv, safe_div(latest_qv-prev_qv, prev_qv) if prev_qv is not None else None),
        ('近7日有效播放', 'Last 7d effective views', p7['total'], None),
        ('近30日有效播放', 'Last 30d effective views', p30['total'], None),
        ('近7日有数据剧目', 'Titles observed in 7d', len(records['last7']['rows']), None)):
        kpis.append(dict(label=label, label_en=en, value=fmt(value), value_en=fmt_en(value), delta=change, wow=None))
    kpis.append(dict(label='近7日 Top3 贡献', label_en='7d top-3 contribution', value=pct(top3), delta=None, wow=None))
    kpis[1].update(sub='较前7日 ' + pct(safe_div(p7['total']-p7['previous'], p7['previous'])),
                   sub_en='vs prior 7d ' + pct(safe_div(p7['total']-p7['previous'], p7['previous'])))
    kpis[2].update(sub='较前30日 ' + pct(safe_div(p30['total']-p30['previous'], p30['previous'])) if p30['previous'] is not None else '前30日暂不可用',
                   sub_en='vs prior 30d ' + pct(safe_div(p30['total']-p30['previous'], p30['previous'])) if p30['previous'] is not None else 'Prior 30d unavailable')
    ins = [f'近7日有效播放 <b>{fmt(p7["total"])}</b>，较前7日变化 <b>{pct(safe_div(p7["total"]-p7["previous"], p7["previous"]))}</b>；全部剧目增量与机构趋势精确对账。',
           f'近7日 Top3 剧目贡献 <b>{pct(top3)}</b>；贡献按所选区间新增播放计算。',
           f'已获取 <b>{len(direct)}</b> 天的逐剧单日实测记录；新版支持按日期回查，旧版缺采区间可在可查范围内补回。']
    ins_en = [f'Last 7d effective views: <b>{fmt_en(p7["total"])}</b>, change vs prior 7d <b>{pct(safe_div(p7["total"]-p7["previous"], p7["previous"]))}</b>. Title increments reconcile exactly to the institution trend.',
              f'The top 3 titles contributed <b>{pct(top3)}</b> of effective-view growth in the selected 7-day period.',
              f'<b>{len(direct)}</b> measured per-title daily records are available. Historical days can now be queried within the platform date limits.']
    if p7['rows']:
        lead = p7['rows'][0]
        ins.append(f'近7日增长第一：<b>{html.escape(lead["name"])}</b>，新增 {fmt(lead["qv"])}，贡献 {pct(lead["share"])}。可结合收藏/千播放与上线时间评估后续素材投入。')
        ins_en.append(f'<b>{html.escape(lead["name"])}</b> led the last 7 days with {fmt_en(lead["qv"])} effective views ({pct(lead["share"])} of growth). Compare favorites per 1K views and launch age before allocating more creative effort.')
    notes = [
        '新版来源：页面日期筛选后实际返回的数据；按剧目 ID、日期范围和完整分页保存，每个区间的播放增量均与机构趋势精确对账。',
        '总播放、完播、分享等字段在新版当前响应中未提供，留空；旧版原始文件完整保留。互动指标来自所选区间的剧目汇总，不能代替独立用户数。',
        '累计明细为本轮查询范围内出现的剧目，按页面当前累计值展示；不能当作历史某天的累计值。Excel 累计列已发现滞后，未用于计算增长。',
        '增长榜、单剧趋势与区间比较只使用新版实测数据。前期若未在对比区间出现该剧，涨幅显示“—”；不把缺失基线当作0，不混入旧版合并档。',
    ]
    notes_en = [
        'Source: responses generated by normal page date selection. Records retain title IDs, explicit date ranges and complete pagination; view increments reconcile exactly to institution trends.',
        'Total views, completions and shares are unavailable in the current v2 responses and remain null. Legacy source files are preserved. Period interactions are event counts, not unique people.',
        'Cumulative details cover titles observed in the queried ranges and reflect the current page totals, not historical day-end balances. Lagging Excel cumulative values are excluded from growth calculations.',
        'Growth boards, title trends and period comparisons use only v2 measurements. Missing prior coverage shows a dash, not a zero baseline. Legacy merged intervals are kept in the archive.',
    ]
    requested_start = manifest.get('requestedStart') or shift(latest, 1-manifest.get('backfillDays', 30))
    missing = [d for d in date_axis(requested_start, latest) if d not in direct]
    if missing:
        notes.append(f'所请求历史范围 {requested_start} ~ {latest} 仍有 {len(missing)} 个单日不可用；详见历史覆盖日历。未获取的日期留空，不用旧合并档补数。')
        notes_en.append(f'{len(missing)} requested days in {requested_start} ~ {latest} remain unavailable. See the coverage calendar. Gaps are not filled with legacy merged snapshots.')
    if 'previous30' not in records:
        notes.append('平台未能返回前30日的对比数据，因此近30日可查看实际增长，但暂不提供月环比。')
        notes_en.append('The platform did not return the prior 30-day period. Actual growth for the last 30 days is available; month-over-month comparison is unavailable.')
    series_history = []
    series_errors = []
    if (root / 'series_latest.json').exists():
        from series_history import upgrade_record, validate_series
        for path in sorted((root / 'series').glob('*.json')):
            try:
                record = upgrade_record(read_json(path))
                validate_series(record)
                if record['id'] != path.stem:
                    raise ValueError('单剧历史文件名与ID不匹配')
            except Exception:
                series_errors.append(path.name)
                continue
            if not record.get('qv'):
                continue
            matched, differences = 0, []
            for day, qv in record['qv'].items():
                source = direct.get(day)
                if source:
                    row = next((r for r in source['rows'] if r['id'] == record['id']), None)
                    if row is not None:
                        matched += 1
                        if row['qv'] != qv:
                            differences.append(dict(date=day, curve=qv, measured=row['qv']))
            series_history.append(dict(id=record['id'], name=record['name'], qv=record['qv'], dur=record.get('dur', {}),
                                       matchedDays=matched, differences=differences,
                                       start=min(record['qv']), end=max(record['qv'])))
        series_history.sort(key=lambda r: -len(r['qv']))
        total_points = sum(len(r['qv']) for r in series_history)
        matched_points = sum(r['matchedDays'] for r in series_history)
        notes.append(f'另保存 {len(series_history)} 部剧的 {total_points} 个单剧播放日值，重合核对 {matched_points} 点。此补充来源单独展示，不增加全机构已验收天数，也不补造未知互动指标。')
        notes_en.append(f'A separate archive contains {total_points} title-day view values across {len(series_history)} titles, with {matched_points} overlapping points checked. It does not increase institution-wide verified-day coverage or supply unavailable interactions.')
        if series_errors:
            notes.append(f'{len(series_errors)} 份单剧补充档案未通过读取校验，暂不展示；主日报数据不受影响。')
            notes_en.append(f'{len(series_errors)} supplemental title archives failed validation and are omitted. Primary report data is unaffected.')
    trend_titles = {d['id']: dict(id=d['id'], name=d['name']) for d in dramas}
    for did, info in catalog.items():
        gid = group_map[did]
        trend_titles.setdefault(gid, dict(id=gid, name=info['name'] if gid == did else gid))
    from series_details import load_details
    detail_errors = []
    details = load_details(root, errors=detail_errors)
    for detail in details:
        detail['accountAudit'] = account_comparison(detail, records, direct)
    if detail_errors:
        notes.append(f'{len(detail_errors)} 份单剧画像/流量档案未通过校验，已暂时隐藏。')
        notes_en.append(f'{len(detail_errors)} audience/traffic snapshots failed validation and are omitted.')
    from episode_details import load_episodes
    episode_errors = []
    episodes = load_episodes(root, errors=episode_errors)
    if episode_errors:
        notes.append(f'{len(episode_errors)} 份分集快照校验失败，暂不展示。')
        notes_en.append(f'{len(episode_errors)} episode snapshots failed validation and are omitted.')
    return dict(schema=2, generated=dt.datetime.now().strftime('%Y-%m-%d %H:%M'), dataThrough=latest,
                snapDate=latest, daily=daily, kpis=kpis, wow=wow_periods[0]['rows'], wowPeriods=wow_periods,
                dramas=dramas, moversSeries=movers, dramaTrends=dict(trends), gaps=gaps,
                insights=ins, insights_en=ins_en, top3Share=top3, periods=periods,
                qualityNotes=notes, qualityNotes_en=notes_en, directDays=len(direct), aiInsights=None,
                legacyDaily=[dict(date=day, **values) for day, values in sorted(history.items())],
                cumulativeScopeDays=cumulative_scope,
                titleCatalog=catalog, groupMap=group_map,
                trendTitles=list(trend_titles.values()),
                seriesHistory=series_history,
                seriesDetails=details,
                episodeDetails=episodes,
                dayDetails={day: [[r['id'], r['qv'], r['like'], r['fav'], r['com']] for r in record['rows']]
                            for day, record in sorted(direct.items())},
                historyRequestedStart=requested_start,
                historyCoverage=[dict(date=d, status='ok' if d in direct else 'institution_only' if d in institution
                                      else ('unavailable' if error_kind(manifest['failedDays'][d]) == 'platform_error' else 'unverified')
                                      if d in manifest.get('failedDays', {}) else 'pending')
                                 for d in date_axis(requested_start, latest)])


def build_report(base):
    from generate_report import ai_insights
    base = Path(base)
    payload = build_payload(base)
    payload['aiInsights'] = ai_insights(payload)
    template = (base / 'template.html').read_text(encoding='utf-8')
    from report_codec import encode_payload
    encoded = encode_payload(payload)
    out = template.replace('/*__DATA__*/null', encoded)
    tmp = base / 'report.html.tmp'
    tmp.write_text(out, encoding='utf-8')
    tmp.replace(base / 'report.html')
    from report_delivery import build_web_report
    build_web_report(base, payload)
    print(f'report.html written; v2 through {payload["dataThrough"]}; {payload["directDays"]} measured drama days; {len(payload["dramas"])} grouped titles')
    return payload
