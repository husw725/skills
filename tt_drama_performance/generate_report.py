#!/usr/bin/env python3
"""Generate report.html from data/ (xlsx snapshots + daily_history.json).

Data sources:
  data/content_performance_YYYY-MM-DD.xlsx  -- per-drama CUMULATIVE snapshot (one per day)
  data/daily_history.json                   -- institution-level per-day metrics {date: {...}}

Per-drama daily increments = diff between consecutive snapshots.
"""
import json, glob, os, re, html, shutil, subprocess
from datetime import datetime, timedelta

import openpyxl

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')


def load_daily():
    p = os.path.join(DATA, 'daily_history.json')
    hist = json.load(open(p)) if os.path.exists(p) else {}
    # seed/merge from backfill dump(s) daily_stats_*.json
    for f in glob.glob(os.path.join(DATA, 'daily_stats_*.json')):
        for row in json.load(open(f)).get('daily', []):
            m = row['metrics']
            hist[row['eventDate']] = {
                'vv': int(m['vv']), 'qv': int(m['innerfeedVv']), 'finish': int(m['vvFinish']),
                'playDur': int(m['playDuration']), 'likes': int(m['likeCnt']),
                'comments': int(m['commentCnt']), 'favs': int(m['favouriteCnt']),
                'shares': int(m['shareCnt']),
            }
    json.dump(hist, open(p, 'w'), indent=1, sort_keys=True)
    return [dict(date=d, **hist[d]) for d in sorted(hist)]


# 导出列按**列名**识别，不按位置。2026-08-24 起平台把 "Total Views/总播放" 列从导出里
# 砍掉了（8 列→7 列），按位置读会把"人均播放时长"当成总播放（实测同口径增量 −3.5 亿）。
# 界面语言不同表头也不同，中英都认。缺列 → None。
HDR = dict(id=('ID',), name=('Drama', '剧集', '剧名'), qv=('Qualified Views', '有效播放量', '合格播放'),
           tv=('Total Views', '总播放量', '总播放'), dur=('Avg. Play Duration Per User', '人均播放时长'),
           fav=('Favorites', '收藏'), com=('Comments', '评论'), like=('Likes', '点赞'))


def read_snapshot(f):
    """{contract_id: dict(name, qv, tv, dur, fav, com, like)}；tv 缺列时为 None。"""
    ws = openpyxl.load_workbook(f).active
    it = ws.iter_rows(values_only=True)
    head = [str(h).strip() if h is not None else '' for h in next(it)]
    col = {}
    for k, names in HDR.items():
        for i, h in enumerate(head):
            if h in names:
                col[k] = i
                break
    if 'id' not in col or 'qv' not in col:
        raise ValueError(f'{os.path.basename(f)} 表头不认识: {head}')
    g = lambda r, k: (r[col[k]] if k in col and col[k] < len(r) else None)
    rows = {}
    for r in it:
        if g(r, 'id') is None:
            continue
        rows[str(g(r, 'id'))] = dict(name=g(r, 'name'), qv=g(r, 'qv') or 0, tv=g(r, 'tv'),
                                    dur=g(r, 'dur') or 0, fav=g(r, 'fav') or 0,
                                    com=g(r, 'com') or 0, like=g(r, 'like') or 0)
    return rows


def load_snapshots():
    snaps = {}
    for f in sorted(glob.glob(os.path.join(DATA, 'content_performance_*.xlsx'))):
        # .candidate.xlsx 是 daily_update 未通过验收的临时导出（正常会被改名或隔离，
        # 崩在中途才会残留）。绝不能当成已验收快照读进来，否则半刷新数据混进增长榜。
        if '.candidate.' in os.path.basename(f):
            continue
        m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(f))
        if not m:
            continue
        snaps[m.group(1)] = read_snapshot(f)
    # 平台数据滞后且偶尔跳更：内容完全相同的相邻快照是同一批数据，只留最早那份，
    # 避免增长榜出现全 0 的假日期档位。
    prev = None
    for d in sorted(snaps):
        if snaps[d] == prev:
            del snaps[d]
        else:
            prev = snaps[d]
    return snaps


def fmt(n):
    if n is None:
        return '-'
    n = float(n)
    sign = '-' if n < 0 else ''
    a = abs(n)
    if a >= 1e8: return f'{sign}{a/1e8:.2f}亿'
    if a >= 1e4: return f'{sign}{a/1e4:.1f}万'
    return f'{sign}{a:,.0f}'


def pct(x, digits=1):
    return '-' if x is None else f'{x*100:.{digits}f}%'


def safe_div(a, b):
    return a / b if b else None


def ai_insights(payload):
    """config.json 里 ai_insights=true 且本机装了 claude CLI 时，让 Claude 写深度洞察；
    任何失败都静默回退（返回 None，报告只保留规则式洞察）。"""
    try:
        cfg = json.load(open(os.path.join(BASE, 'config.json'), encoding='utf-8'))
    except FileNotFoundError:
        return None
    if not cfg.get('ai_insights'):
        return None
    exe = shutil.which('claude')
    if not exe:
        print('claude CLI 未找到，跳过 AI 洞察')
        return None
    digest = dict(
        数据截至=payload['dataThrough'],
        最近14天=[{'日期': r['date'], '总播放': r['vv'], '合格播放': r['qv'], '完播': r['finish'],
                  '点赞': r['likes'], '收藏': r['favs'], '分享': r['shares']} for r in payload['daily'][-14:]],
        周期环比=[{p['label']: p['rows']} for p in payload['wowPeriods']],
        剧目Top8=[{'剧目': d['name'], '累计合格播放': d['qv'],
                  '互动率(每合格播放)': d['engage'], '人均时长s': d['dur']}
                 for d in payload['dramas'][:8]],
        最新单日剧目增量=payload['moversSeries'][-1] if payload['moversSeries'] else None,
    )
    prompt = (
        '你是一名资深短剧行业 BI 分析师。基于下面的 TikTok 短剧运营数据(JSON)，'
        '写 4-6 条深度洞察。要求：每条 1-2 句话、必须引用具体数字、'
        '聚焦趋势拐点/结构变化/内容集中度/互动质量/异常点，并尽量给出可执行建议；'
        '不要复述表面数字，要给判断。'
        '只输出一个 JSON 字符串数组（如 ["洞察1","洞察2"]），不要 markdown 代码块，不要其他文字。\n\n'
        + json.dumps(digest, ensure_ascii=False, default=str)
    )
    try:
        # prompt 走 stdin：Windows 上 claude.cmd 经 cmd.exe 执行，命令行上限 8191 字符，
        # 几 KB 的数据摘要作参数必超限。显式 utf-8 避免 Windows 默认 GBK 解码失败。
        # 每日定时批量调用，显式用便宜模型。
        r = subprocess.run([exe, '-p', '--model', 'sonnet'], input=prompt,
                           capture_output=True, text=True, encoding='utf-8', timeout=300)
        out = r.stdout.strip()
        items = json.loads(out[out.index('['):out.rindex(']') + 1])
        items = [str(x) for x in items if isinstance(x, str) and x.strip()][:8]
        print(f'AI 洞察 {len(items)} 条')
        return items or None
    except Exception as e:
        print(f'AI 洞察失败（{e.__class__.__name__}: {e}），使用规则式洞察')
        return None


def build():
    daily = load_daily()
    snaps = load_snapshots()
    snap_dates = sorted(snaps)
    latest_snap = snaps[snap_dates[-1]]

    # ---- KPIs: latest day vs previous, 7d vs prior 7d ----
    last, prev = daily[-1], daily[-2] if len(daily) > 1 else None
    w1 = daily[-7:]
    w0 = daily[-14:-7]

    def wsum(w, k):
        return sum(r[k] for r in w)

    def wow(k):
        return safe_div(wsum(w1, k) - wsum(w0, k), wsum(w0, k)) if len(w0) == 7 else None

    def eng(r):
        return safe_div(r['likes'] + r['comments'] + r['favs'] + r['shares'], r['vv'])

    kpis = [
        dict(label='总播放 (最新日)', value=fmt(last['vv']),
             delta=safe_div(last['vv'] - prev['vv'], prev['vv']) if prev else None, wow=wow('vv')),
        dict(label='合格播放 (最新日)', value=fmt(last['qv']),
             delta=safe_div(last['qv'] - prev['qv'], prev['qv']) if prev else None, wow=wow('qv')),
        dict(label='合格率', value=pct(safe_div(last['qv'], last['vv'])),
             delta=None, wow=None,
             sub=f"7日均 {pct(safe_div(wsum(w1,'qv'), wsum(w1,'vv')))}"),
        dict(label='完播量', value=fmt(last['finish']),
             delta=safe_div(last['finish'] - prev['finish'], prev['finish']) if prev else None, wow=wow('finish')),
        dict(label='互动率', value=pct(eng(last), 2),
             delta=None, wow=None,
             sub=f"前一日 {pct(eng(prev), 2) if prev else '-'}"),
        dict(label='单次播放时长', value=f"{last['playDur']/last['vv']:.1f}s" if last['vv'] else '-',
             delta=None, wow=None,
             sub=f"7日均 {wsum(w1,'playDur')/wsum(w1,'vv'):.1f}s" if wsum(w1, 'vv') else ''),
    ]

    # ---- Period-over-period tables (7d = 周环比, 30d = 月环比), shown when data suffices ----
    METRIC_LABELS = [('vv', '总播放'), ('qv', '合格播放'), ('finish', '完播量'),
                     ('likes', '点赞'), ('comments', '评论'), ('favs', '收藏'), ('shares', '分享')]

    def period_rows(n):
        a, b = daily[-n:], daily[-2 * n:-n]
        if len(a) < n or len(b) < n:
            return None
        rows = []
        for k, lab in METRIC_LABELS:
            s1, s0 = sum(r[k] for r in a), sum(r[k] for r in b)
            rows.append(dict(metric=lab, w1=fmt(s1), w0=fmt(s0), chg=safe_div(s1 - s0, s0)))
        return rows

    wow_periods = [dict(label=f'近{n}日', n=n, rows=period_rows(n)) for n in (7, 30)]
    wow_periods = [p for p in wow_periods if p['rows']]
    wow_rows = wow_periods[0]['rows'] if wow_periods else []

    # ---- Drama table (latest snapshot), with user-defined grouping ----
    try:
        groups = {k: v for k, v in
                  json.load(open(os.path.join(BASE, 'groups.json'), encoding='utf-8')).items()
                  if not k.startswith('_')}
    except FileNotFoundError:
        groups = {}
    member2group = {str(m): g for g, ms in groups.items() for m in ms}

    try:
        dmeta = json.load(open(os.path.join(DATA, 'drama_meta.json'), encoding='utf-8'))
    except FileNotFoundError:
        dmeta = {}

    raw = []
    for did, r in latest_snap.items():
        raw.append(dict(
            id=did, name=r['name'], qv=r['qv'], dur=r['dur'],
            launch=dmeta.get(str(did), {}).get('launch'),
            fav=r['fav'], com=r['com'], like=r['like'],
            # 剧目级导出已无总播放列（2026-08-24 起），比率一律以合格播放为分母
            engage=safe_div(r['like'] + r['com'] + r['fav'], r['qv']),
            fav1k=safe_div(r['fav'] * 1000, r['qv']),
        ))

    def group_of(d):
        return member2group.get(d['id']) or member2group.get(str(d['name']))

    merged = {}
    for d in sorted(raw, key=lambda d: -d['qv']):
        g = group_of(d)
        key = g or d['id']
        e = merged.setdefault(key, dict(id=key, name=g or d['name'], qv=0,
                                        fav=0, com=0, like=0, _durw=0, members=[]))
        for k in ('qv', 'fav', 'com', 'like'):
            e[k] += d[k]
        e['_durw'] += (d['dur'] or 0) * (d['qv'] or 0)
        e['members'].append(d)
    dramas = []
    for e in merged.values():
        e['dur'] = round(e['_durw'] / e['qv']) if e['qv'] else 0
        del e['_durw']
        # 合并组的上线时间取最新成员的（"最近上新"视角，配合默认按上线排序）
        e['launch'] = max((m['launch'] for m in e['members'] if m.get('launch')), default=None)
        e['engage'] = safe_div(e['like'] + e['com'] + e['fav'], e['qv'])
        e['fav1k'] = safe_div(e['fav'] * 1000, e['qv'])
        if len(e['members']) == 1:
            e['members'] = []
        dramas.append(e)
    dramas.sort(key=lambda d: -d['qv'])
    total_qv = sum(d['qv'] for d in dramas)
    top3_share = safe_div(sum(d['qv'] for d in dramas[:3]), total_qv)

    # ---- Per-drama movers: one entry per consecutive snapshot pair ----
    movers_series = []
    drama_trends = {}   # 组名 -> [{d, qv, days}]，单剧趋势图数据源
    for i in range(1, len(snap_dates)):
        d0 = datetime.strptime(snap_dates[i - 1], '%Y-%m-%d')
        d1 = datetime.strptime(snap_dates[i], '%Y-%m-%d')
        prev_snap, cur_snap = snaps[snap_dates[i - 1]], snaps[snap_dates[i]]
        agg = {}
        for did, r in cur_snap.items():
            # 新上的剧在前一份快照里没有记录：基线记 0，首日增量=首日累计，榜上标"新"
            p = prev_snap.get(did) or dict(qv=0, like=0, fav=0)
            g = member2group.get(did) or member2group.get(str(r['name'])) or r['name']
            e = agg.setdefault(g, dict(name=g, d_qv=0, d_like=0, d_fav=0, qv0=0, qv1=0, launch=None))
            lc = dmeta.get(str(did), {}).get('launch')
            if lc and (e['launch'] is None or lc > e['launch']):
                e['launch'] = lc
            e['d_qv'] += r['qv'] - p['qv']
            e['d_like'] += r['like'] - p['like']
            e['d_fav'] += r['fav'] - p['fav']
            e['qv0'] += p['qv']   # 起始累计合格播放（涨幅分母）
            e['qv1'] += r['qv']   # 期末累计合格播放
        for m in agg.values():
            drama_trends.setdefault(m['name'], []).append(
                dict(d=snap_dates[i], qv=m['d_qv'], days=(d1 - d0).days))
        ranked = sorted(agg.values(), key=lambda m: -m['d_qv'])
        cutoff = (d1 - timedelta(days=14)).date().isoformat()
        for m in ranked:
            m['new7'] = bool(m['launch'] and m['launch'] >= cutoff)
        # 14天内新剧即使没进前10也固定追加在榜尾（带"新"标）
        rows = ranked[:10] + [m for m in ranked[10:] if m['new7']]
        # totQv 是**全部剧目**的合计，不是榜上展示行的合计——缺采声明里要拿它当
        # "这个合计是准的"的依据，用截断后的 rows 求和会少算掉榜外剧目。
        movers_series.append(dict(
            frm=snap_dates[i - 1], to=snap_dates[i], days=(d1 - d0).days, rows=rows,
            totQv=sum(m['d_qv'] for m in ranked)))

    # ---- Auto insights (senior-BI voice) ----
    ins = []
    peak = max(daily, key=lambda r: r['vv'])
    ins.append(f"周期内总播放峰值出现在 <b>{peak['date']}</b>（{fmt(peak['vv'])}），当日合格率 {pct(safe_div(peak['qv'], peak['vv']))}。")
    if len(w0) == 7:
        d_vv, d_qv = wow('vv'), wow('qv')
        arrow = '回升' if d_vv > 0 else '回落'
        ins.append(f"近7日总播放较前7日<b>{arrow} {pct(abs(d_vv))}</b>，合格播放变化 {pct(d_qv)}"
                   f"（{'合格播放跑赢大盘，流量质量在改善' if d_qv > d_vv else '合格播放弱于大盘，需关注流量质量'}）。")
        qr1, qr0 = safe_div(wsum(w1, 'qv'), wsum(w1, 'vv')), safe_div(wsum(w0, 'qv'), wsum(w0, 'vv'))
        ins.append(f"合格率近7日 <b>{pct(qr1)}</b> vs 前7日 {pct(qr0)}，"
                   f"{'结构性提升' if qr1 > qr0 else '有所下滑，建议排查低质流量来源'}。")
    if top3_share:
        ins.append(f"内容集中度：Top3 短剧贡献了 <b>{pct(top3_share)}</b> 的合格播放"
                   f"{'，头部依赖偏高，建议培育腰部内容' if top3_share > 0.6 else '，组合相对健康'}"
                   f"（Top1：{html.escape(str(dramas[0]['name']))}，{fmt(dramas[0]['qv'])}）。")
    med_qv = sorted(d['qv'] for d in dramas)[len(dramas)//2]
    weak = [d for d in dramas if d['qv'] > med_qv and (d['engage'] or 0) < 0.02 and d['qv'] > 50000]
    if weak:
        names = '、'.join(html.escape(str(d['name'])) for d in weak[:3])
        ins.append(f"<b>高流量低互动</b>预警：{names} 合格播放高于中位数但互动率不足 2%，转化效率待提升。")
    if len(snap_dates) < 2:
        ins.append("剧目级日增量需要至少两天的快照才能计算，从明天起将自动出现「单日增长榜」。")

    # ---- 缺采日：机构级趋势里有、但剧目级没有单独档位的日期 ----
    # 平台的剧目导出永远是"当前"全量累计，没有按历史日期回查的入口，所以这些日期的
    # 剧目级切分是永久拿不到的（不是本地漏采）。只能如实标出来——绝不能把合并区间的
    # 量按天数摊平，那是凭空造数。合计值仍然是准的，一并给出来。
    gaps = []
    for s in movers_series:
        if s['days'] <= 1:
            continue
        d1 = datetime.strptime(s['to'], '%Y-%m-%d')
        missing = [(d1 - timedelta(days=k)).date().isoformat() for k in range(s['days'] - 1, 0, -1)]
        gaps.append(dict(frm=s['frm'], to=s['to'], days=s['days'], missing=missing,
                         qv=s['totQv']))
    if gaps:
        miss_all = [d for g in gaps for d in g['missing']]
        ins.append(f"数据完整性：剧目级缺 <b>{'、'.join(miss_all)}</b> 共 {len(miss_all)} 天的单日切分"
                   f"（平台把相邻日合并下发，导出只有当前累计、无法回查历史某天）。"
                   f"这些区间在增长榜按合计展示，趋势图上以虚线标出日均估算（非实测）。")

    payload = dict(
        generated=datetime.now().strftime('%Y-%m-%d %H:%M'),
        dataThrough=daily[-1]['date'], snapDate=snap_dates[-1],
        daily=daily, kpis=kpis, wow=wow_rows, wowPeriods=wow_periods, dramas=dramas,
        moversSeries=movers_series, dramaTrends=drama_trends, gaps=gaps,
        insights=ins, top3Share=top3_share,
    )
    payload['aiInsights'] = ai_insights(payload)

    tpl = open(os.path.join(BASE, 'template.html'), encoding='utf-8').read()
    out = tpl.replace('/*__DATA__*/null', json.dumps(payload, ensure_ascii=False, default=str))
    open(os.path.join(BASE, 'report.html'), 'w', encoding='utf-8').write(out)
    print('report.html written;', len(daily), 'days,', len(dramas), 'dramas,', len(snap_dates), 'snapshot(s)')


if __name__ == '__main__':
    build()
