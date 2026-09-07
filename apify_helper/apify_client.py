"""调用 Apify 上的 rainminer/tiktok-short-drama-scraper，并把结果解析成统一结构。"""
import datetime as dt
import re
import time

import requests

ACTOR = "rainminer~tiktok-short-drama-scraper"
BASE = "https://api.apify.com/v2"
PRICE_PER_ITEM_USD = 0.00199  # Free 档单价，付费套餐更低；只用于日志里的费用估算
EP_URL_RE = re.compile(r"/shortdrama/episode/(\d+)/(\d+)")


class ApifyError(RuntimeError):
    pass


def episode_url(sid):
    return f"https://www.tiktok.com/shortdrama/episode/{sid}/1"


def run(series_ids, token, max_items=500, use_proxy=False, timeout=900, poll=5):
    """跑一次 actor，所有剧塞进同一个 run。返回 (run_id, items)。"""
    payload = {
        "startUrls": [{"url": episode_url(s)} for s in series_ids],
        "maxItems": int(max_items),
        "scrapeRelatedDramas": False,
        "region": "US",
        "proxyConfiguration": ({"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}
                               if use_proxy else {"useApifyProxy": False}),
    }
    r = requests.post(f"{BASE}/acts/{ACTOR}/runs", params={"token": token, "waitForFinish": 60},
                      json=payload, timeout=120)
    if r.status_code >= 400:
        raise ApifyError(f"启动失败 HTTP {r.status_code}: {r.text[:300]}")
    run_info = r.json()["data"]
    deadline = time.time() + timeout
    while run_info["status"] in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(poll)
        rr = requests.get(f"{BASE}/actor-runs/{run_info['id']}", params={"token": token}, timeout=60)
        rr.raise_for_status()
        run_info = rr.json()["data"]
    if run_info["status"] in ("READY", "RUNNING"):
        # 本地等待超时：主动中止云端 run，否则它继续跑、继续计费，下次重试还会并发第二个
        try:
            requests.post(f"{BASE}/actor-runs/{run_info['id']}/abort", params={"token": token}, timeout=30)
        except requests.RequestException:
            pass
        raise ApifyError(f"run {run_info['id']} 超过 {timeout}s 未完成，已发送中止")
    if run_info["status"] != "SUCCEEDED":
        raise ApifyError(f"run {run_info['id']} 状态 {run_info['status']}")
    di = requests.get(f"{BASE}/datasets/{run_info['defaultDatasetId']}/items",
                      params={"token": token, "clean": "true", "format": "json"}, timeout=180)
    di.raise_for_status()
    return run_info["id"], di.json()


# ---------- 解析 ----------
def _get(item, *paths):
    """按顺序尝试多个字段路径；同时兼容嵌套 dict、点号扁平键、斜杠扁平键。"""
    for p in paths:
        for key in (p, p.replace(".", "/")):
            if key in item and item[key] not in (None, ""):
                return item[key]
        cur = item
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, ""):
            return cur
    return None


def _int(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().upper().replace(",", "")
    mult = 1
    for suf, mlt in (("K", 1e3), ("M", 1e6), ("B", 1e9)):
        if s.endswith(suf):
            s, mult = s[:-1], mlt
            break
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "free", "preview")
    return bool(v)


def _iso(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return dt.datetime.utcfromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    return str(v)[:19].replace("T", " ")


def parse_item(item):
    url = _get(item, "webVideoUrl", "url") or ""
    mm = EP_URL_RE.search(url)
    sid = _get(item, "shortDramaSeriesInfo.seriesId", "seriesId") or (mm.group(1) if mm else None)
    ep = _int(_get(item, "shortDramaSeriesInfo.episodeNumber", "episodeNumber")) or (int(mm.group(2)) if mm else None)
    if not sid or not ep:
        return None
    genres = _get(item, "shortDramaSeriesInfo.genres", "genres")
    if isinstance(genres, list):
        genres = " / ".join(str(g) for g in genres)
    return {
        "series_id": str(sid),
        "episode_number": ep,
        "video_id": str(_get(item, "id", "videoId") or ""),
        "play": _int(_get(item, "playCount", "stats.playCount", "views")),
        "digg": _int(_get(item, "diggCount", "likeCount", "stats.diggCount")),
        "comment": _int(_get(item, "commentCount", "stats.commentCount")),
        "share": _int(_get(item, "shareCount", "stats.shareCount")),
        "collect": _int(_get(item, "collectCount", "favoriteCount", "stats.collectCount")),
        "duration": _int(_get(item, "videoMeta.duration", "duration")),
        "is_preview": _bool(_get(item, "shortDramaSeriesInfo.isPreview", "shortDramaSeriesInfo.isFree", "isPreview")),
        "created_at": _iso(_get(item, "createTimeISO", "createTime")),
        "cover_url": _get(item, "videoMeta.coverUrl", "imageUrl", "videoMeta.cover", "coverUrl"),
        "url": url,
        "meta": {
            "title": _get(item, "shortDramaSeriesInfo.seriesTitle", "shortDramaSeriesInfo.title", "text"),
            "synopsis": _get(item, "shortDramaSeriesInfo.synopsis", "shortDramaSeriesInfo.description"),
            "genres": genres,
            "episode_count": _int(_get(item, "shortDramaSeriesInfo.episodeCount")),
            "author_name": _get(item, "authorMeta.name", "authorMeta.uniqueId"),
            "author_nick": _get(item, "authorMeta.nickName", "authorMeta.nickname"),
            "author_fans": _int(_get(item, "authorMeta.fans", "authorMeta.followerCount")),
        },
    }


def parse_items(items):
    """-> {series_id: {"meta": {...}, "episodes": [...]}}，集按序号去重排序，元数据优先取第 1 集。"""
    out = {}
    for raw in items or []:
        p = parse_item(raw) if isinstance(raw, dict) else None
        if not p:
            continue
        s = out.setdefault(p["series_id"], {"meta": {}, "episodes": {}})
        s["episodes"][p["episode_number"]] = p
        if p["episode_number"] == 1 or not s["meta"].get("title"):
            s["meta"] = {**s["meta"], **{k: v for k, v in p["meta"].items() if v not in (None, "")}}
            if p["cover_url"] and (p["episode_number"] == 1 or not s["meta"].get("cover_url")):
                s["meta"]["cover_url"] = p["cover_url"]
    for s in out.values():
        s["episodes"] = [s["episodes"][k] for k in sorted(s["episodes"])]
    return out
