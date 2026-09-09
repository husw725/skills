"""SQLite 存储与指标计算。所有页面只读本地库，抓取由 app.py 的后台任务写入。"""
import datetime as dt
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS series(
  series_id     TEXT PRIMARY KEY,
  title         TEXT DEFAULT '',
  synopsis      TEXT DEFAULT '',
  genres        TEXT DEFAULT '',
  episode_count INTEGER,
  cover_url     TEXT DEFAULT '',
  author_name   TEXT DEFAULT '',
  author_nick   TEXT DEFAULT '',
  author_fans   INTEGER,
  grp           TEXT DEFAULT '自家',
  notes         TEXT DEFAULT '',
  status        TEXT DEFAULT 'pending',   -- pending / ok / error
  status_msg    TEXT DEFAULT '',
  archived      INTEGER DEFAULT 0,
  added_at      TEXT,
  updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS snapshot(
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  taken_at  TEXT NOT NULL,
  job_id    INTEGER,
  items     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshot_series ON snapshot(series_id, taken_at);
CREATE TABLE IF NOT EXISTS episode_stat(
  snapshot_id    INTEGER NOT NULL,
  series_id      TEXT NOT NULL,
  episode_number INTEGER NOT NULL,
  video_id       TEXT,
  play    INTEGER, digg INTEGER, comment INTEGER, share INTEGER, collect INTEGER,
  duration INTEGER, is_preview INTEGER, created_at TEXT, cover_url TEXT, url TEXT,
  PRIMARY KEY(snapshot_id, episode_number)
);
CREATE TABLE IF NOT EXISTS job(
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger      TEXT,
  started_at   TEXT,
  finished_at  TEXT,
  status       TEXT,        -- running / ok / error
  series_count INTEGER,
  items        INTEGER,
  run_id       TEXT,
  error        TEXT,
  cost_usd     REAL
);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""

EP_COLS = ("snapshot_id", "series_id", "episode_number", "video_id", "play", "digg", "comment",
           "share", "collect", "duration", "is_preview", "created_at", "cover_url", "url")
META_COLS = ("title", "synopsis", "genres", "episode_count", "cover_url",
             "author_name", "author_nick", "author_fans")


def now_iso():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_ours(grp):
    """分组 自家 / 自家-US / 自家-BR 都算自家。"""
    return bool(grp) and grp.startswith("自家")


def safe_div(a, b):
    try:
        return a / b if a is not None and b else None
    except TypeError:
        return None


class DB:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()  # ponytail: 单进程全局锁，几十部剧的读写量用不着连接池
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    # ---------- 基础 ----------
    def q(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=()):
        with self._lock:
            self.conn.execute(sql, args)
            self.conn.commit()

    def kv_get(self, k, default=None):
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return r["v"] if r else default

    def kv_set(self, k, v):
        self.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, v))

    # ---------- 剧 ----------
    def add_series(self, sid, grp):
        self.x("INSERT OR IGNORE INTO series(series_id,grp,status,status_msg,added_at,updated_at) "
               "VALUES(?,?,?,?,?,?)", (sid, grp, "pending", "抓取中", now_iso(), now_iso()))

    def get_series(self, sid):
        return self.one("SELECT * FROM series WHERE series_id=?", (sid,))

    def list_series(self, include_archived=False):
        where = "" if include_archived else "WHERE archived=0"
        return self.q(f"SELECT * FROM series {where} ORDER BY added_at DESC")

    def set_series_status(self, sid, status, msg=""):
        self.x("UPDATE series SET status=?, status_msg=?, updated_at=? WHERE series_id=?",
               (status, msg, now_iso(), sid))

    def set_series_fields(self, sid, **fields):
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE series SET {sets}, updated_at=? WHERE series_id=?",
               (*fields.values(), now_iso(), sid))

    def delete_series(self, sid):
        with self._lock:
            self.conn.execute("DELETE FROM episode_stat WHERE series_id=?", (sid,))
            self.conn.execute("DELETE FROM snapshot WHERE series_id=?", (sid,))
            self.conn.execute("DELETE FROM series WHERE series_id=?", (sid,))
            self.conn.commit()

    # ---------- 快照写入 ----------
    def save_snapshot(self, sid, parsed, job_id, taken_at=None):
        """parsed = {"meta": {...}, "episodes": [{...}]}，见 apify_client.parse_items。"""
        taken_at = taken_at or now_iso()
        eps = parsed["episodes"]
        rows = []
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO snapshot(series_id,taken_at,job_id,items) VALUES(?,?,?,?)",
                (sid, taken_at, job_id, len(eps)))
            snap_id = cur.lastrowid
            for e in eps:
                rows.append((snap_id, sid, e["episode_number"], e.get("video_id"),
                             e.get("play"), e.get("digg"), e.get("comment"), e.get("share"),
                             e.get("collect"), e.get("duration"), 1 if e.get("is_preview") else 0,
                             e.get("created_at"), e.get("cover_url"), e.get("url")))
            self.conn.executemany(
                f"INSERT OR REPLACE INTO episode_stat({','.join(EP_COLS)}) "
                f"VALUES({','.join('?' * len(EP_COLS))})", rows)
            meta = {k: v for k, v in parsed.get("meta", {}).items() if k in META_COLS and v not in (None, "")}
            if meta:
                sets = ", ".join(f"{k}=?" for k in meta)
                self.conn.execute(f"UPDATE series SET {sets}, updated_at=? WHERE series_id=?",
                                  (*meta.values(), now_iso(), sid))
            self.conn.commit()
        return snap_id

    # ---------- 快照读取 ----------
    def latest_snapshot(self, sid):
        return self.one("SELECT * FROM snapshot WHERE series_id=? ORDER BY taken_at DESC, id DESC LIMIT 1", (sid,))

    def prev_day_snapshot(self, sid, before):
        """比 before 早至少一个自然日的最近一次快照，用来算日增量。"""
        return self.one("SELECT * FROM snapshot WHERE series_id=? AND date(taken_at) < date(?) "
                        "ORDER BY taken_at DESC, id DESC LIMIT 1", (sid, before))

    def episodes(self, snap_id):
        return self.q("SELECT * FROM episode_stat WHERE snapshot_id=? ORDER BY episode_number", (snap_id,))

    def snap_totals(self, snap_id):
        return self.one("SELECT COUNT(*) n, SUM(play) play, SUM(digg) digg, SUM(comment) comment, "
                        "SUM(share) share, SUM(collect) collect FROM episode_stat WHERE snapshot_id=?", (snap_id,))

    # ---------- 指标 ----------
    def series_metrics(self, s):
        m = dict(s)
        m.update(total_play=None, delta_play=None, prev_taken_at=None, first_play=None, last_play=None,
                 retention=None, paywall_ep=None, cliff=None, eng_rate=None, collect_rate=None,
                 last_taken_at=None, snap_id=None, ep_n=0, stale=False)
        snap = self.latest_snapshot(s["series_id"])
        if not snap:
            return m
        eps = self.episodes(snap["id"])
        if not eps:
            return m
        tot = self.snap_totals(snap["id"])
        m["snap_id"], m["last_taken_at"], m["ep_n"] = snap["id"], snap["taken_at"], len(eps)
        m["total_play"] = tot["play"] or 0
        first, last = eps[0], eps[-1]
        m["first_play"], m["last_play"] = first["play"], last["play"]
        m["retention"] = safe_div(last["play"], first["play"])
        free = [e for e in eps if e["is_preview"]]
        if free:
            pw = max(e["episode_number"] for e in free)
            m["paywall_ep"] = pw
            last_free = next(e for e in eps if e["episode_number"] == pw)
            paid = [e for e in eps if e["episode_number"] > pw]
            if paid:
                m["cliff"] = safe_div(last_free["play"], paid[0]["play"])
        eng = sum((tot[k] or 0) for k in ("digg", "comment", "share", "collect"))
        m["eng_rate"] = safe_div(eng, tot["play"])
        m["collect_rate"] = safe_div(tot["collect"], tot["play"])
        prev = self.prev_day_snapshot(s["series_id"], snap["taken_at"])
        if prev:
            pt = self.snap_totals(prev["id"])
            m["delta_play"] = (tot["play"] or 0) - (pt["play"] or 0)
            m["prev_taken_at"] = prev["taken_at"]
        try:
            age = dt.datetime.now() - dt.datetime.strptime(snap["taken_at"], "%Y-%m-%d %H:%M:%S")
            m["stale"] = age.total_seconds() > 48 * 3600
        except ValueError:
            pass
        return m

    def overview(self, include_archived=False):
        # ponytail: 每部剧 4 条小查询，百部以内毫秒级；上千部再改成一次聚合
        return [self.series_metrics(s) for s in self.list_series(include_archived)]

    def trend_by_group(self, days=30):
        """每天每部剧取当日最后一次快照的总播放，按分组求和。"""
        # ponytail: 某天没抓的剧当天不计入，剧数变动会让曲线跳；要平滑再做前向填充
        return self.q("""
            WITH daily AS (
              SELECT series_id, date(taken_at) d, MAX(id) snap_id FROM snapshot GROUP BY series_id, d
            ), tot AS (
              SELECT snapshot_id, SUM(play) play FROM episode_stat GROUP BY snapshot_id
            )
            SELECT daily.d, series.grp, SUM(tot.play) play, COUNT(*) n
            FROM daily JOIN series ON series.series_id=daily.series_id
            JOIN tot ON tot.snapshot_id=daily.snap_id
            WHERE daily.d >= date('now','localtime',?) AND series.archived=0
            GROUP BY daily.d, series.grp ORDER BY daily.d""", (f"-{days} days",))

    def dashboard(self, ov):
        active = [m for m in ov if m["status"] == "ok" and m["snap_id"]]
        ours = [m for m in active if is_ours(m["grp"])]

        def avg(vals):
            vals = [v for v in vals if v is not None]
            return sum(vals) / len(vals) if vals else None

        deltas = [m["delta_play"] for m in active if m["delta_play"] is not None]
        kpi = {
            "n_series": len(active), "n_ours": len(ours),
            "total_play": sum(m["total_play"] or 0 for m in active),
            "delta_play": sum(deltas) if deltas else None,
            "avg_first_play": avg([m["first_play"] for m in ours]),
            "avg_retention": avg([m["retention"] for m in ours]),
            "avg_eng": avg([m["eng_rate"] for m in ours]),
            "avg_collect": avg([m["collect_rate"] for m in ours]),
        }
        top = sorted([m for m in active if m["delta_play"] is not None],
                     key=lambda m: -m["delta_play"])[:5]
        # 抓取失败 / 过期不在首页告警，运营看数据；失败原因在操作台的剧管理状态列和抓取日志里
        return {"kpi": kpi, "top": top, "trend": self.trend_by_group()}

    def series_trend(self, sid):
        return self.q("""SELECT s.id, s.taken_at, SUM(e.play) play,
                                SUM(COALESCE(e.digg,0)+COALESCE(e.comment,0)+COALESCE(e.share,0)+COALESCE(e.collect,0)) eng
                         FROM snapshot s JOIN episode_stat e ON e.snapshot_id=s.id
                         WHERE s.series_id=? GROUP BY s.id ORDER BY s.taken_at, s.id""", (sid,))

    def episode_rows(self, m):
        """最新快照的集列表，附留存与互动率。"""
        if not m["snap_id"]:
            return []
        eps = self.episodes(m["snap_id"])
        first = eps[0]["play"] if eps else None
        for e in eps:
            e["retention"] = safe_div(e["play"], first)
            eng = sum((e[k] or 0) for k in ("digg", "comment", "share", "collect"))
            e["eng_rate"] = safe_div(eng, e["play"])
            e["collect_rate"] = safe_div(e["collect"], e["play"])
        return eps

    def episode_history(self, sid, ep):
        rows = self.q("""SELECT s.taken_at, e.* FROM episode_stat e JOIN snapshot s ON s.id=e.snapshot_id
                         WHERE e.series_id=? AND e.episode_number=? ORDER BY s.taken_at, s.id""", (sid, ep))
        # 日增量：每天取最后一条，和前一天相减
        by_day = {}
        for r in rows:
            by_day[r["taken_at"][:10]] = r
        days = sorted(by_day)
        deltas = []
        for i in range(1, len(days)):
            a, b = by_day[days[i - 1]], by_day[days[i]]
            deltas.append({"d": days[i], "play": (b["play"] or 0) - (a["play"] or 0),
                           "digg": (b["digg"] or 0) - (a["digg"] or 0),
                           "collect": (b["collect"] or 0) - (a["collect"] or 0)})
        return rows, deltas

    # ---------- 任务 ----------
    def create_job(self, trigger, n):
        with self._lock:
            cur = self.conn.execute("INSERT INTO job(trigger,started_at,status,series_count) VALUES(?,?,?,?)",
                                    (trigger, now_iso(), "running", n))
            self.conn.commit()
            return cur.lastrowid

    def finish_job(self, job_id, status, items=None, run_id=None, error=None, cost=None):
        self.x("UPDATE job SET finished_at=?, status=?, items=?, run_id=?, error=?, cost_usd=? WHERE id=?",
               (now_iso(), status, items, run_id, error, cost, job_id))

    def list_jobs(self, limit=30):
        return self.q("SELECT * FROM job ORDER BY id DESC LIMIT ?", (limit,))
