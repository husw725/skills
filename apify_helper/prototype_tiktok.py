"""TikTok Accounts API 接入原型（仅用于申请权限时的录屏演示，全部假数据，不发任何外部请求）。
路由前缀 /connect ；ponytail: 内存字典存已连接账号，重启即清空，演示够用。
"""
import random
import time

from flask import Blueprint, redirect, render_template, request, url_for

bp = Blueprint("proto", __name__, url_prefix="/connect", template_folder="templates")

APP_NAME = "Starlit Shorts Analytics (Internal)"
SCOPES = [
    ("Basic account information", "Display name, avatar, follower count of the authorized account"),
    ("Video list and performance data", "Views, reach, watch time, full-video-watched rate of your own videos"),
    ("Audience insights", "Aggregated gender and country distribution of viewers, traffic sources"),
]
MOCK_ACCOUNTS = {
    "starlit.shorts": {"name": "Starlit Shorts", "followers": 1_284_000, "business_id": "ba_7f3a9c21"},
    "starlit.drama.en": {"name": "Starlit Drama EN", "followers": 402_500, "business_id": "ba_c19e02d7"},
}
TITLES = ["Mighty Tyrant, Tender Love · Ep {}", "Contract Bride · Ep {}", "The CEO's Secret Twin · Ep {}"]
_connected = {}  # handle -> connected_at


@bp.app_template_filter("num_en")
def num_en(v):
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{int(round(v)):,}"


def _videos(handle, n=8):
    rnd = random.Random(handle)
    out = []
    for i in range(1, n + 1):
        views = rnd.randint(80_000, 2_400_000)
        avg = rnd.uniform(18, 52)
        male = rnd.randint(18, 45)
        out.append({
            "id": f"7{rnd.randint(10**17, 10**18 - 1)}",
            "title": TITLES[i % 3].format(i),
            "posted": f"2026-08-{rnd.randint(10, 28):02d}",
            "video_views": views,
            "reach": int(views * rnd.uniform(0.62, 0.88)),
            "average_time_watched": avg,
            "full_video_watched_rate": rnd.uniform(0.22, 0.61),
            "total_time_watched_h": round(views * avg / 3600),
            "audience_genders": {"Female": 100 - male, "Male": male},
            "audience_countries": [("US", rnd.randint(38, 62)), ("GB", rnd.randint(6, 12)), ("CA", rnd.randint(4, 9)), ("AU", rnd.randint(3, 7))],
            "impression_sources": [("For You", rnd.randint(55, 80)), ("Following", rnd.randint(5, 15)), ("Search", rnd.randint(3, 10)), ("Profile", rnd.randint(2, 8))],
        })
    return out


@bp.route("/")
def home():
    accounts = [{"handle": h, **MOCK_ACCOUNTS[h], "connected_at": t} for h, t in _connected.items()]
    return render_template("proto/home.html", app_name=APP_NAME, accounts=accounts, just=request.args.get("connected"))


@bp.route("/authorize")
def authorize():
    """模拟 TikTok 授权确认页。真实流程中这一页由 TikTok 托管，这里只演示用户看到什么、同意什么。"""
    handles = [h for h in MOCK_ACCOUNTS if h not in _connected]
    return render_template("proto/authorize.html", app_name=APP_NAME, scopes=SCOPES, handles=handles,
                           redirect_uri=url_for("proto.callback", _external=True))


@bp.route("/callback")
def callback():
    handle = request.args.get("account")
    if request.args.get("decision") == "allow" and handle in MOCK_ACCOUNTS:
        _connected[handle] = time.strftime("%Y-%m-%d %H:%M")
        return redirect(url_for("proto.home", connected=handle))
    return redirect(url_for("proto.home"))


@bp.route("/<handle>/videos")
def videos(handle):
    if handle not in _connected:
        return redirect(url_for("proto.home"))
    acc = {"handle": handle, **MOCK_ACCOUNTS[handle]}
    vids = _videos(handle)
    tot_views = sum(v["video_views"] for v in vids)
    summary = {
        "videos": len(vids), "views": tot_views,
        "avg_watch": sum(v["average_time_watched"] * v["video_views"] for v in vids) / tot_views,
        "full_rate": sum(v["full_video_watched_rate"] * v["video_views"] for v in vids) / tot_views,
        "female": sum(v["audience_genders"]["Female"] * v["video_views"] for v in vids) / tot_views,
    }
    return render_template("proto/videos.html", app_name=APP_NAME, acc=acc, videos=vids, summary=summary)


@bp.route("/<handle>/disconnect", methods=["POST"])
def disconnect(handle):
    _connected.pop(handle, None)
    return redirect(url_for("proto.home"))
