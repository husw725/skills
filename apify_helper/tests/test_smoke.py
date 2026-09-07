"""用假 Apify 返回跑通整条链路：解析 → 入库 → 指标 → 页面。无需 token、无需网络。
运行：python tests/test_smoke.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="apify_helper_test_")
os.environ["APIFY_HELPER_DB"] = os.path.join(TMP, "t.sqlite")
os.environ["APIFY_HELPER_CONFIG"] = os.path.join(TMP, "config.json")
pathlib.Path(os.environ["APIFY_HELPER_CONFIG"]).write_text(json.dumps({"apify_token": "test-token"}), "utf-8")

import app as A  # noqa: E402
import apify_client  # noqa: E402

SID_A, SID_B, SID_C = "7677865695564436501", "7700000000000000002", "7700000000000000003"
PLAYS_A = [100000, 80000, 70000, 30000, 27000, 25000, 24000, 23000, 22000, 21000]  # 前 3 集免费，第 4 集断崖
PLAYS_B = [50000, 45000, 42000, 40000, 20000, 19000, 18000, 17000]                 # 前 4 集免费


def nested_item(sid, ep, play, preview, count):
    return {"id": f"{sid}{ep:03d}", "text": "Mighty Tyrant", "textLanguage": "en",
            "webVideoUrl": f"https://www.tiktok.com/shortdrama/episode/{sid}/{ep}",
            "playCount": play, "diggCount": play // 20, "commentCount": play // 200, "shareCount": play // 500,
            "collectCount": play // 50,
            "authorMeta": {"name": "ours_acc", "nickName": "Ours", "fans": 1300000},
            "videoMeta": {"duration": 77, "coverUrl": f"https://img.test/{sid}/{ep}.jpg"},
            "shortDramaSeriesInfo": {"seriesId": sid, "seriesTitle": "Mighty Tyrant, Tender Love", "synopsis": "A tyrant.",
                                     "episodeNumber": ep, "episodeCount": count, "genres": ["Forced Love", "CEO"],
                                     "isPreview": preview},
            "createTimeISO": "2026-08-20T10:00:00.000Z"}


def flat_item(sid, ep, play, preview, count):
    return {"id": f"{sid}{ep:03d}", "webVideoUrl": f"https://www.tiktok.com/shortdrama/episode/{sid}/{ep}",
            "playCount": str(play), "diggCount": "1.2K", "commentCount": 30, "shareCount": 5, "collectCount": 400,
            "shortDramaSeriesInfo/seriesId": sid, "shortDramaSeriesInfo/seriesTitle": "Rival Drama",
            "shortDramaSeriesInfo/episodeNumber": ep, "shortDramaSeriesInfo/episodeCount": count,
            "shortDramaSeriesInfo/genres": "Revenge", "shortDramaSeriesInfo/isPreview": "true" if preview else "false",
            "authorMeta/name": "rival_acc", "authorMeta/fans": 5000, "videoMeta/duration": 60,
            "imageUrl": f"https://img.test/{sid}/cover.jpg", "createTime": 1755680400}


def make_items(scale=1.0):
    items = [nested_item(SID_A, i + 1, int(p * scale), i < 3, len(PLAYS_A)) for i, p in enumerate(PLAYS_A)]
    items += [flat_item(SID_B, i + 1, int(p * scale), i < 4, len(PLAYS_B)) for i, p in enumerate(PLAYS_B)]
    items.append(nested_item(SID_A, 5, int(PLAYS_A[4] * scale), False, len(PLAYS_A)))  # 重复行，应去重
    return items


def fake_run_factory(scale):
    def fake_run(sids, token, max_items=500, use_proxy=False, **_):
        assert token == "test-token", "token 未从 config 读到"
        assert max_items == 500
        return f"run_{scale}", make_items(scale)
    return fake_run


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))


def main():
    # 1) 解析器：嵌套 / 扁平 / 仅 URL 三种形态
    parsed = apify_client.parse_items(make_items() + [{"webVideoUrl": f"https://www.tiktok.com/shortdrama/episode/{SID_C}/2", "playCount": 9}])
    assert set(parsed) == {SID_A, SID_B, SID_C}, parsed.keys()
    assert len(parsed[SID_A]["episodes"]) == 10 and len(parsed[SID_B]["episodes"]) == 8
    assert parsed[SID_A]["meta"]["genres"] == "Forced Love / CEO"
    assert parsed[SID_A]["meta"]["cover_url"].endswith("/1.jpg"), "封面应取第 1 集"
    b1 = parsed[SID_B]["episodes"][0]
    assert b1["digg"] == 1200 and b1["play"] == 50000 and b1["is_preview"] is True
    assert b1["created_at"].startswith("2025-08-20"), b1["created_at"]
    assert parsed[SID_B]["episodes"][4]["is_preview"] is False
    assert parsed[SID_C]["episodes"][0]["episode_number"] == 2
    print("parse ok")

    # 2) 入库 + 第一次快照
    db = A.db
    for sid, grp in ((SID_A, "自家"), (SID_B, "竞品"), (SID_C, "自家")):
        db.add_series(sid, grp)
    A.apify_client.run = fake_run_factory(1.0)
    job1 = A.run_job([SID_A, SID_B, SID_C], "add", taken_at="2026-09-01 09:00:00")
    j = db.one("SELECT * FROM job WHERE id=?", (job1,))
    assert j["status"] == "ok" and j["items"] == 18, dict(j)
    assert db.get_series(SID_A)["status"] == "ok" and db.get_series(SID_A)["title"] == "Mighty Tyrant, Tender Love"
    assert db.get_series(SID_C)["status"] == "error", "没抓到的剧应标记失败"

    mA = db.series_metrics(db.get_series(SID_A))
    assert mA["total_play"] == sum(PLAYS_A) and mA["ep_n"] == 10
    assert mA["paywall_ep"] == 3 and approx(mA["cliff"], 70000 / 30000)
    assert approx(mA["retention"], 21000 / 100000)
    assert mA["delta_play"] is None, "只有一次快照不该有日增"
    eng = sum(p // 20 + p // 200 + p // 500 + p // 50 for p in PLAYS_A)
    assert approx(mA["eng_rate"], eng / sum(PLAYS_A))
    print("snapshot1 ok")

    # 3) 第二天快照 → 日增量
    A.apify_client.run = fake_run_factory(1.1)
    A.run_job([SID_A, SID_B], "schedule", taken_at="2026-09-02 09:00:00")
    A.apify_client.run = fake_run_factory(1.1)
    A.run_job([SID_A], "manual", taken_at="2026-09-02 15:00:00")  # 同日再刷，日增应仍对比 09-01
    mA = db.series_metrics(db.get_series(SID_A))
    exp_delta = sum(int(p * 1.1) for p in PLAYS_A) - sum(PLAYS_A)
    assert mA["delta_play"] == exp_delta and mA["prev_taken_at"] == "2026-09-01 09:00:00", (mA["delta_play"], exp_delta)
    ov = db.overview()
    dash = db.dashboard(ov)
    mB = next(m for m in ov if m["series_id"] == SID_B)
    assert dash["kpi"]["delta_play"] == exp_delta + mB["delta_play"]
    assert dash["kpi"]["n_series"] == 2 and dash["kpi"]["n_ours"] == 1
    assert dash["top"][0]["series_id"] == SID_A
    assert any(a["level"] == "critical" and a["sid"] == SID_C for a in dash["alerts"])
    assert {r["grp"] for r in dash["trend"]} == {"自家", "竞品"}
    hist, deltas = db.episode_history(SID_A, 4)
    assert len(hist) == 3 and len(deltas) == 1 and deltas[0]["play"] == int(30000 * 1.1) - 30000
    print("snapshot2 / dashboard ok")

    # 4) 页面
    A.start_job = lambda sids, trig: (True, f"stub {len(sids)}")
    c = A.app.test_client()
    for path, needle in (("/", "在追剧数"), (f"/series/{SID_A}", "付费墙断崖"), (f"/series/{SID_A}?compare={SID_B}", "Rival Drama"),
                         (f"/series/{SID_A}/episode/4", "付费墙后第一集"), ("/admin", "抓取日志"), (f"/series/{SID_C}", "还没有数据")):
        r = c.get(path)
        body = r.get_data(as_text=True)
        assert r.status_code == 200 and needle in body, (path, r.status_code)
        assert "built-in method" not in body and "{{" not in body, f"{path} 模板渲染出了原始对象"
    r = c.get(f"/export/series/{SID_A}.csv")
    assert r.status_code == 200 and "剧ID" in r.get_data(as_text=True) and r.get_data(as_text=True).count("\n") == 11
    assert c.get("/series/nope").status_code == 404 and c.get(f"/series/{SID_A}/episode/99").status_code == 404
    assert c.get("/api/status").get_json()["running"] is False
    print("pages ok")

    # 5) 操作台表单
    r = c.post("/admin/add", data={"ids": f"7700000000000000009\nhttps://www.tiktok.com/shortdrama/episode/7700000000000000010/3\nabc", "grp": "竞品"})
    assert r.status_code == 302 and "2" in r.headers["Location"] and "1" in r.headers["Location"]
    assert db.get_series("7700000000000000010")["grp"] == "竞品" and db.get_series("7700000000000000010")["status"] == "pending"
    c.post(f"/admin/series/{SID_B}", data={"action": "save", "grp": "竞品", "grp_custom": "韩剧对标", "notes": "n1"})
    assert db.get_series(SID_B)["grp"] == "韩剧对标" and db.get_series(SID_B)["notes"] == "n1"
    c.post(f"/admin/series/{SID_B}", data={"action": "archive"})
    assert db.get_series(SID_B)["archived"] == 1 and len(db.list_series()) == 4
    c.post("/admin/settings", data={"max_items": "300", "use_proxy": "on", "schedule_time": "10:30"})
    cfg = A.load_config()
    assert cfg["apify_token"] == "test-token" and cfg["max_items"] == 300 and cfg["use_proxy"] and not cfg["schedule_enabled"] and cfg["schedule_time"] == "10:30"
    c.post(f"/admin/series/{SID_C}", data={"action": "delete"})
    assert db.get_series(SID_C) is None
    print("admin ok")
    print("ALL OK")


if __name__ == "__main__":
    main()
