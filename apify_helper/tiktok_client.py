"""自建抓取：直接调 tiktok.com 网页端的短剧接口（无需登录、无需签名，2026-09 实测）。
接口：
  GET /api/drama/detail/            ?dramaID=...            → dramaInfo（剧名、简介、题材、总集数、作者）
  GET /api/drama/episode/item_list/ ?dramaID=...&cursor&count → itemList（每集 stats / 时长 / 发布时间 / 免费标记）
输出结构与 apify_client.parse_items 一致：{series_id: {"meta": {...}, "episodes": [...]}}
"""
import datetime as dt
import time

import requests

BASE = "https://www.tiktok.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
COMMON = {"aid": "1988", "app_language": "en", "language": "en", "region": "US", "storeRegion": "US"}
PAGE = 50


class DirectError(RuntimeError):
    pass


def _session(proxy):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": f"{BASE}/shortdrama/", "Accept": "application/json"})
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def fetch_json(session, path, params, timeout=30):
    r = session.get(f"{BASE}{path}", params={**COMMON, **params}, timeout=timeout)
    if r.status_code != 200 or not r.content:
        raise DirectError(f"{path} HTTP {r.status_code}，空响应或被拦截；国内网络请在设置里填代理")
    try:
        d = r.json()
    except ValueError as e:
        raise DirectError(f"{path} 返回非 JSON（可能是验证页）: {r.text[:80]}") from e
    if d.get("statusCode", d.get("status_code", 0)) not in (0, None):
        raise DirectError(f"{path} statusCode={d.get('statusCode')} {d.get('statusMsg') or d.get('status_msg')}")
    return d


def _int(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _iso(ts):
    try:
        return dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_detail(d):
    di = d.get("dramaInfo") or {}
    au = di.get("author") or {}
    user, stats = au.get("user") or {}, au.get("stats") or {}
    return {
        "title": di.get("dramaName"),
        "synopsis": di.get("description"),
        "genres": " / ".join(t.get("tagVal", "") for t in di.get("themes") or [] if t.get("tagVal")) or None,
        "episode_count": _int(di.get("numVideos")),
        "author_name": user.get("uniqueId"),
        "author_nick": user.get("nickname"),
        "author_fans": _int(stats.get("followerCount")),
        "num_watched": _int(di.get("numWatched")),
    }


def parse_items(sid, items):
    eps = {}
    for it in items or []:
        dv = ((it.get("dramaInfo") or {}).get("DramaVideoData")) or {}
        ep = _int(dv.get("EpisodeNumber"))
        if not ep:
            continue
        st = it.get("statsV2") or it.get("stats") or {}
        vid = it.get("video") or {}
        eps[ep] = {
            "series_id": sid, "episode_number": ep, "video_id": str(it.get("id") or ""),
            "play": _int(st.get("playCount")), "digg": _int(st.get("diggCount")),
            "comment": _int(st.get("commentCount")), "share": _int(st.get("shareCount")),
            "collect": _int(st.get("collectCount")),
            "duration": _int(vid.get("duration")),
            "is_preview": bool(dv.get("IsPreview")) or bool(dv.get("IsFreeIntro")),
            "created_at": _iso(it.get("createTime")),
            "cover_url": vid.get("cover") or vid.get("originCover") or None,
            "url": f"{BASE}/shortdrama/episode/{sid}/{ep}",
        }
    return [eps[k] for k in sorted(eps)]


def fetch_series(sid, proxy="", max_items=500, delay=1.0, session=None):
    """抓一部剧。返回 {"meta": {...}, "episodes": [...]}，失败抛 DirectError。"""
    s = session or _session(proxy)
    meta = parse_detail(fetch_json(s, "/api/drama/detail/", {"dramaID": sid}))
    items, cursor = [], "0"
    while len(items) < max_items:
        time.sleep(delay)
        d = fetch_json(s, "/api/drama/episode/item_list/",
                       {"dramaID": sid, "cursor": cursor, "count": min(PAGE, max_items - len(items))})
        batch = d.get("itemList") or []
        items.extend(batch)
        if not d.get("hasMore") or not batch:
            break
        cursor = str(d.get("cursor") or len(items))
    eps = parse_items(sid, items)
    if not eps and not meta.get("title"):
        raise DirectError("剧不存在或该地区不可见")
    return {"meta": meta, "episodes": eps}


def run(series_ids, proxy="", max_items=500, delay=1.0):
    """逐部抓取，单部失败不影响其他。返回 (results, errors)。"""
    s = _session(proxy)
    results, errors = {}, {}
    for sid in series_ids:
        try:
            results[sid] = fetch_series(sid, proxy, max_items, delay, session=s)
        except (DirectError, requests.RequestException) as e:
            errors[sid] = str(e)[:200]
    return results, errors
