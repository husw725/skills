"""短剧数据台：Flask 服务 + 后台抓取线程 + 每日定时。局域网访问，无登录。"""
import csv
import datetime as dt
import io
import json
import os
import re
import socket
import threading
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

import apify_client
import tiktok_client
from db import DB

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("APIFY_HELPER_CONFIG", BASE_DIR / "config.json"))
DEFAULTS = {
    "host": "0.0.0.0", "port": 8765,
    "source": "apify",          # apify | direct
    "apify_token": "",
    "max_items": 500,
    "use_proxy": False,
    "direct_proxy": "",         # 自建模式走的 HTTP 代理，如 http://127.0.0.1:7890；国内机器必填
    "direct_delay": 1.0,        # 自建模式每次请求间隔秒
    "schedule_enabled": True,
    "schedule_time": "09:00",
    "db_path": "data.sqlite",
}
GROUPS = ["自家", "竞品"]
SID_RE = re.compile(r"^\d{10,25}$")
# ponytail: 自家剧清单是静态文件（Drama Center 接口带登录态+签名，程序拉不到）；新剧上线手动更新
OWN_PATH = BASE_DIR / "own_series.json"


def load_own():
    try:
        return json.loads(OWN_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text("utf-8")))
        except json.JSONDecodeError as e:
            print(f"[config] {CONFIG_PATH} 解析失败: {e}，使用默认值")
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


_cfg = load_config()
_db_path = os.environ.get("APIFY_HELPER_DB") or _cfg["db_path"]
db = DB(str(_db_path if os.path.isabs(_db_path) else BASE_DIR / _db_path))

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True
from prototype_tiktok import bp as _proto_bp  # noqa: E402  录屏原型，全假数据
app.register_blueprint(_proto_bp)


# ---------- 模板过滤器 ----------
def fmt_num(v):
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.1f}万"
    return f"{int(round(v)):,}"


def fmt_delta(v):
    if v is None:
        return "—"
    return ("+" if v >= 0 else "−") + fmt_num(abs(v))


def fmt_pct(v, digits=1):
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def fmt_x(v):
    return "—" if v is None else f"{v:.1f}×"


def fmt_time(v):
    return "—" if not v else str(v)[5:16]


def fmt_dur(v):
    if v is None:
        return "—"
    return f"{int(v) // 60}:{int(v) % 60:02d}"


for name, fn in (("num", fmt_num), ("delta", fmt_delta), ("pct", fmt_pct), ("x", fmt_x),
                 ("t", fmt_time), ("dur", fmt_dur)):
    app.jinja_env.filters[name] = fn


# ---------- 抓取任务 ----------
_job_lock = threading.Lock()
_current = {"running": False, "job_id": None, "sids": [], "started_at": None}


def _is_avatar(url):
    """早期自建模式拿不到剧封面时用过账号头像兜底，这里识别出来清掉。"""
    return bool(url) and ("-avt-" in url or "avatar" in url)


def _apply_results(sids, parsed, errors, job_id, taken_at):
    n = 0
    own_cover = {o["id"]: o.get("cover") for o in load_own()}
    for sid in sids:
        p = parsed.get(sid)
        if p and p["episodes"]:
            cur = db.get_series(sid)
            # 自家剧用 Drama Center 海报（本地文件）；其它剧公开接口没有封面，宁可空着走渐变底也不用头像
            if own_cover.get(sid):
                p["meta"]["cover_url"] = own_cover[sid]
            elif cur and _is_avatar(cur["cover_url"]):
                db.set_series_fields(sid, cover_url="")   # save_snapshot 跳过空值，这里直接清
            db.save_snapshot(sid, p, job_id, taken_at)
            db.set_series_status(sid, "ok", "")
            n += len(p["episodes"])
        else:
            db.set_series_status(sid, "error", errors.get(sid) or
                                 "本次未抓到数据：检查剧 ID 是否正确，或到设置里打开代理后重试")
    return n


def run_job(sids, trigger, taken_at=None):
    """同步跑一次抓取。线上由 start_job 放进线程；测试直接调用。按 config.source 分发到 Apify 或自建。"""
    cfg = load_config()
    job_id = db.create_job(trigger, len(sids))
    _current.update(running=True, job_id=job_id, sids=list(sids), started_at=time.time())
    try:
        if cfg.get("source") == "direct":
            parsed, errors = tiktok_client.run(sids, cfg.get("direct_proxy", ""), cfg["max_items"],
                                               float(cfg.get("direct_delay", 1.0)))
            if not parsed and errors:
                raise RuntimeError("自建抓取全部失败：" + next(iter(errors.values())))
            n = _apply_results(sids, parsed, errors, job_id, taken_at)
            db.finish_job(job_id, "ok", items=n, run_id="direct", cost=0.0)
        else:
            if not cfg["apify_token"]:
                raise RuntimeError("未配置 Apify token，请到操作台 → 设置 填写，或把数据源切到自建")
            run_id, items = apify_client.run(sids, cfg["apify_token"], cfg["max_items"], cfg["use_proxy"])
            n = _apply_results(sids, apify_client.parse_items(items), {}, job_id, taken_at)
            db.finish_job(job_id, "ok", items=n, run_id=run_id, cost=round(n * apify_client.PRICE_PER_ITEM_USD, 4))
    except Exception as e:  # noqa: BLE001 任何失败都要落日志并标记剧状态
        db.finish_job(job_id, "error", error=str(e)[:500])
        for sid in sids:
            s = db.get_series(sid)
            if s and s["status"] == "pending":
                db.set_series_status(sid, "error", f"抓取失败：{e}"[:200])
    finally:
        _current.update(running=False)
    return job_id


def start_job(sids, trigger):
    sids = [s for s in sids if s]
    if not sids:
        return False, "没有可刷新的剧"
    if not _job_lock.acquire(blocking=False):
        return False, "已有抓取任务在运行，请稍候"

    def target():
        try:
            run_job(sids, trigger)
        finally:
            _job_lock.release()

    threading.Thread(target=target, daemon=True, name="apify-job").start()
    return True, f"已开始抓取 {len(sids)} 部剧"


def scheduler_loop():
    while True:
        try:
            cfg = load_config()
            if cfg.get("schedule_enabled"):
                now = dt.datetime.now()
                today = now.strftime("%Y-%m-%d")
                # 用 >= 而不是 ==：机器 9 点没开、10 点开机也会补跑当天
                if now.strftime("%H:%M") >= cfg.get("schedule_time", "09:00") and db.kv_get("last_sched") != today:
                    ok, _ = start_job([s["series_id"] for s in db.list_series()], "schedule")
                    if ok:
                        db.kv_set("last_sched", today)
        except Exception as e:  # noqa: BLE001
            print("[scheduler]", e)
        time.sleep(30)


# ---------- 页面 ----------
@app.route("/")
def index():
    ov = db.overview()
    dash = db.dashboard(ov)
    groups = GROUPS + sorted({m["grp"] for m in ov} - set(GROUPS))
    payload = {"trend": dash["trend"], "top": [{"title": m["title"] or m["series_id"], "delta": m["delta_play"],
                                                 "grp": m["grp"], "sid": m["series_id"]} for m in dash["top"]]}
    return render_template("index.html", ov=ov, dash=dash, groups=groups, payload=payload,
                           n_pending=sum(1 for m in ov if m["status"] == "pending"))


@app.route("/series/<sid>")
def series_page(sid):
    s = db.get_series(sid)
    if not s:
        abort(404)
    m = db.series_metrics(s)
    eps = db.episode_rows(m)
    trend = db.series_trend(sid)
    others = [x for x in db.list_series() if x["series_id"] != sid and x["status"] == "ok"]
    cmp_sid = request.args.get("compare") or ""
    cmp_m, cmp_eps = None, []
    if cmp_sid:
        cs = db.get_series(cmp_sid)
        if cs:
            cmp_m = db.series_metrics(cs)
            cmp_eps = db.episode_rows(cmp_m)
    payload = {
        "eps": [{"ep": e["episode_number"], "play": e["play"], "ret": e["retention"], "eng": e["eng_rate"],
                 "collect": e["collect_rate"], "preview": bool(e["is_preview"])} for e in eps],
        "paywall": m["paywall_ep"],
        "trend": [{"t": r["taken_at"], "play": r["play"], "eng": r["eng"]} for r in trend],
        "cmp": {"title": cmp_m["title"] or cmp_sid, "eps": [{"ep": e["episode_number"], "ret": e["retention"]} for e in cmp_eps]} if cmp_m else None,
        "title": m["title"] or sid,
    }
    return render_template("series.html", s=m, eps=eps, others=others, cmp=cmp_m, cmp_sid=cmp_sid, payload=payload)


@app.route("/series/<sid>/episode/<int:ep>")
def episode_page(sid, ep):
    s = db.get_series(sid)
    if not s:
        abort(404)
    m = db.series_metrics(s)
    eps = db.episode_rows(m)
    cur = next((e for e in eps if e["episode_number"] == ep), None)
    if not cur:
        abort(404)
    rank = sorted(eps, key=lambda e: -(e["play"] or 0)).index(cur) + 1
    hist, deltas = db.episode_history(sid, ep)
    last_delta = deltas[-1]["play"] if deltas else None
    prev_ep = next((e for e in eps if e["episode_number"] == ep - 1), None)
    next_ep = next((e for e in eps if e["episode_number"] == ep + 1), None)
    payload = {"hist": [{"t": r["taken_at"], "play": r["play"], "digg": r["digg"], "comment": r["comment"],
                         "share": r["share"], "collect": r["collect"]} for r in hist],
               "deltas": deltas, "title": f"{m['title'] or sid} 第{ep}集"}
    return render_template("episode.html", s=m, e=cur, ep=ep, rank=rank, n=len(eps), hist=hist, deltas=deltas,
                           last_delta=last_delta, prev_ep=prev_ep, next_ep=next_ep, payload=payload)


@app.route("/admin")
def admin():
    cfg = load_config()
    ov = db.overview(include_archived=True)
    tok = cfg["apify_token"]
    token_hint = f"已配置（末四位 {tok[-4:]}）" if tok else "未配置"
    have = {m["series_id"] for m in ov}
    own = [{**o, "added": o["id"] in have} for o in load_own()]
    return render_template("admin.html", cfg=cfg, ov=ov, jobs=db.list_jobs(), groups=GROUPS, own=own,
                           token_hint=token_hint, msg=request.args.get("msg", ""), running=_current["running"])


@app.route("/admin/add_own", methods=["POST"])
def admin_add_own():
    """从内置自家剧清单添加：sid=单部，sid=all 加全部未添加的。分组 自家-地区，备注写发布账号。"""
    want = request.form.get("sid", "")
    have = {m["series_id"] for m in db.list_series(include_archived=True)}
    picked = [o for o in load_own() if o["id"] not in have and (want == "all" or o["id"] == want)]
    for o in picked:
        db.add_series(o["id"], f"自家-{o['region']}")
        db.set_series_fields(o["id"], notes=o["account"], title=o["title"], cover_url=o.get("cover"))
    msg = f"已添加 {len(picked)} 部剧" if picked else "没有新增（已在系统里）"
    if picked:
        _, m2 = start_job([o["id"] for o in picked], "add")
        msg += f"；{m2}"
    return redirect(url_for("admin", msg=msg))


@app.route("/admin/add", methods=["POST"])
def admin_add():
    raw = request.form.get("ids", "")
    grp = (request.form.get("grp_custom") or request.form.get("grp") or "自家").strip()
    ids, bad = [], []
    for tok in re.split(r"[\s,，;；]+", raw):
        tok = tok.strip()
        if not tok:
            continue
        mm = apify_client.EP_URL_RE.search(tok)
        if mm:
            tok = mm.group(1)
        (ids if SID_RE.match(tok) else bad).append(tok)
    for sid in ids:
        db.add_series(sid, grp)
        db.set_series_fields(sid, grp=grp, archived=0)
    msg = f"已添加 {len(ids)} 部剧"
    if bad:
        msg += f"；{len(bad)} 条不是有效的剧 ID：{', '.join(bad[:3])}"
    if ids:
        ok, m2 = start_job(ids, "add")
        msg += f"；{m2}"
    return redirect(url_for("admin", msg=msg))


@app.route("/admin/series/<sid>", methods=["POST"])
def admin_series(sid):
    action = request.form.get("action", "save")
    if not db.get_series(sid):
        abort(404)
    if action == "delete":
        db.delete_series(sid)
        msg = "已删除"
    elif action == "archive":
        db.set_series_fields(sid, archived=1)
        msg = "已归档"
    elif action == "unarchive":
        db.set_series_fields(sid, archived=0)
        msg = "已恢复"
    elif action == "refresh":
        _, msg = start_job([sid], "manual")
    else:
        grp = (request.form.get("grp_custom") or request.form.get("grp") or "").strip() or None
        db.set_series_fields(sid, grp=grp, notes=request.form.get("notes"))
        msg = "已保存"
    return redirect(url_for("admin", msg=msg))


@app.route("/admin/refresh", methods=["POST"])
def admin_refresh():
    _, msg = start_job([s["series_id"] for s in db.list_series()], "manual")
    return redirect(url_for("admin", msg=msg))


@app.route("/admin/settings", methods=["POST"])
def admin_settings():
    cfg = load_config()
    tok = request.form.get("apify_token", "").strip()
    if tok:
        cfg["apify_token"] = tok
    try:
        cfg["max_items"] = max(1, min(10000, int(request.form.get("max_items", cfg["max_items"]))))
    except ValueError:
        pass
    cfg["use_proxy"] = request.form.get("use_proxy") == "on"
    if request.form.get("source") in ("apify", "direct"):
        cfg["source"] = request.form["source"]
    cfg["direct_proxy"] = request.form.get("direct_proxy", cfg.get("direct_proxy", "")).strip()
    try:
        cfg["direct_delay"] = max(0.0, min(30.0, float(request.form.get("direct_delay", cfg.get("direct_delay", 1.0)))))
    except ValueError:
        pass
    cfg["schedule_enabled"] = request.form.get("schedule_enabled") == "on"
    st = request.form.get("schedule_time", "").strip()
    if re.match(r"^\d{2}:\d{2}$", st):
        cfg["schedule_time"] = st
    save_config(cfg)
    return redirect(url_for("admin", msg="设置已保存"))


@app.route("/api/status")
def api_status():
    job = db.one("SELECT * FROM job WHERE id=?", (_current["job_id"],)) if _current["job_id"] else None
    return jsonify({"running": _current["running"], "job": job,
                    "elapsed": int(time.time() - _current["started_at"]) if _current["running"] and _current["started_at"] else None})


@app.route("/export/series/<sid>.csv")
def export_series(sid):
    s = db.get_series(sid)
    if not s:
        abort(404)
    m = db.series_metrics(s)
    eps = db.episode_rows(m)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["剧ID", "剧名", "集数", "播放", "点赞", "评论", "分享", "收藏", "留存(相对第1集)", "互动率",
                "免费集", "时长秒", "发布时间", "链接", "快照时间"])
    for e in eps:
        w.writerow([sid, m["title"], e["episode_number"], e["play"], e["digg"], e["comment"], e["share"], e["collect"],
                    f"{e['retention']:.4f}" if e["retention"] is not None else "",
                    f"{e['eng_rate']:.4f}" if e["eng_rate"] is not None else "",
                    "是" if e["is_preview"] else "", e["duration"], e["created_at"], e["url"], m["last_taken_at"]])
    fname = f"{sid}_{(m['last_taken_at'] or '')[:10]}.csv"
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


if __name__ == "__main__":
    cfg = load_config()
    if not CONFIG_PATH.exists():
        save_config(cfg)
    threading.Thread(target=scheduler_loop, daemon=True, name="scheduler").start()
    print("短剧数据台已启动，局域网访问地址：")
    for ip in lan_ips() or ["<本机IP>"]:
        print(f"  http://{ip}:{cfg['port']}/")
    print(f"  本机：http://127.0.0.1:{cfg['port']}/   操作台：/admin   Ctrl+C 停止")
    app.run(host=cfg["host"], port=int(cfg["port"]), threaded=True, debug=False)
