"""自建直连模式：用 2026-09-07 抓到的真实响应（裁剪版）验证解析，再用假 HTTP 跑通 run_job 的 direct 分支。
运行：python tests/test_direct.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="apify_helper_direct_")
os.environ["APIFY_HELPER_DB"] = os.path.join(TMP, "t.sqlite")
os.environ["APIFY_HELPER_CONFIG"] = os.path.join(TMP, "config.json")
pathlib.Path(os.environ["APIFY_HELPER_CONFIG"]).write_text(
    json.dumps({"source": "direct", "direct_proxy": "", "direct_delay": 0, "schedule_enabled": False}), "utf-8")

import app as A  # noqa: E402
import tiktok_client as T  # noqa: E402

FX = ROOT / "tests" / "fixtures"
DETAIL = json.loads((FX / "direct_detail.json").read_text("utf-8"))
ITEMS = json.loads((FX / "direct_item_list.json").read_text("utf-8"))
SID = "7677865695564436501"


def main():
    # 1) 解析真实响应
    meta = T.parse_detail(DETAIL)
    assert meta["title"] == "Mighty Tyrant, Tender Love" and meta["episode_count"] == 30
    assert meta["genres"].startswith("Forced Love") and meta["author_name"] == "mialopez2249"
    assert meta["author_fans"] == 1500000 and "cover_fallback" not in meta, "不再用头像兜底"
    eps = T.parse_items(SID, ITEMS["itemList"])
    assert [e["episode_number"] for e in eps] == [1, 2, 3, 15, 16]
    e1 = eps[0]
    assert e1["play"] == 349400 and e1["digg"] == 13300 and e1["collect"] == 7604 and e1["share"] == 1345
    assert e1["duration"] == 77 and e1["is_preview"] is True and e1["created_at"].startswith("2026-08-")
    assert eps[3]["is_preview"] is True and eps[4]["is_preview"] is False, "第 15 集免费、第 16 集付费"
    assert e1["url"] == f"https://www.tiktok.com/shortdrama/episode/{SID}/1"
    print("parse ok")

    # 2) 假 HTTP：分页 + 错误隔离
    calls = []

    def fake_fetch(session, path, params, timeout=30):
        calls.append((path, params.get("dramaID"), params.get("cursor")))
        if params.get("dramaID") == "bad":
            raise T.DirectError("剧不存在")
        if path.endswith("/detail/"):
            return DETAIL
        if params["cursor"] == "0":
            return {"itemList": ITEMS["itemList"][:3], "hasMore": True, "cursor": "3"}
        return {"itemList": ITEMS["itemList"][3:], "hasMore": False, "cursor": "5"}

    T.fetch_json = fake_fetch
    res, errs = T.run([SID, "bad"], proxy="", max_items=500, delay=0)
    assert SID in res and len(res[SID]["episodes"]) == 5 and "bad" in errs
    assert [c for c in calls if c[1] == SID and c[0].endswith("item_list/")] == \
           [("/api/drama/episode/item_list/", SID, "0"), ("/api/drama/episode/item_list/", SID, "3")]
    print("pagination / isolation ok")

    # 3) run_job 走 direct 分支，落库、状态、封面兜底、费用为 0
    db = A.db
    db.add_series(SID, "自家")
    db.add_series("bad", "竞品")
    job_id = A.run_job([SID, "bad"], "manual", taken_at="2026-09-07 09:00:00")
    j = db.one("SELECT * FROM job WHERE id=?", (job_id,))
    assert j["status"] == "ok" and j["items"] == 5 and j["run_id"] == "direct" and j["cost_usd"] == 0.0, dict(j)
    s = db.get_series(SID)
    assert s["status"] == "ok" and s["title"] == "Mighty Tyrant, Tender Love" and s["cover_url"] == "", "非自家剧没有封面"
    assert s["genres"].startswith("Forced Love") and s["episode_count"] == 30
    assert db.get_series("bad")["status"] == "error" and "剧不存在" in db.get_series("bad")["status_msg"]
    m = db.series_metrics(s)
    assert m["paywall_ep"] == 15 and m["total_play"] == sum(e["play"] for e in eps)
    # 已有真实封面保留；老库里残留的头像封面被清掉
    db.set_series_fields(SID, cover_url="https://img.test/real.jpg")
    A.run_job([SID], "manual", taken_at="2026-09-08 09:00:00")
    assert db.get_series(SID)["cover_url"] == "https://img.test/real.jpg"
    db.set_series_fields(SID, cover_url="https://p16-sign-va.tiktokcdn.com/tos-maliva-avt-0068/abc~c5_720x720.jpeg")
    A.run_job([SID], "manual", taken_at="2026-09-08 10:00:00")
    assert db.get_series(SID)["cover_url"] == "", "头像封面应被清空"
    print("run_job direct ok")

    # 4) 设置页切换数据源
    c = A.app.test_client()
    body = c.get("/admin").get_data(as_text=True)
    assert "自建直连 TikTok" in body and 'value="direct" checked' in body
    c.post("/admin/settings", data={"source": "apify", "max_items": "500", "direct_proxy": "http://127.0.0.1:7890", "direct_delay": "2"})
    cfg = A.load_config()
    assert cfg["source"] == "apify" and cfg["direct_proxy"] == "http://127.0.0.1:7890" and cfg["direct_delay"] == 2.0
    c.post("/admin/settings", data={"source": "direct", "max_items": "500", "direct_proxy": "", "direct_delay": "0"})
    assert A.load_config()["source"] == "direct"
    print("settings ok")
    print("ALL OK")


if __name__ == "__main__":
    main()
