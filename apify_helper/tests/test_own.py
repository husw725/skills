"""自家剧清单：页面渲染 + 单部/全部添加 + 重复添加不覆盖。python tests/test_own.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APIFY_HELPER_DB"] = os.path.join(tempfile.mkdtemp(), "t.sqlite")
import app as A

calls = []
A.start_job = lambda sids, trig: calls.append(list(sids)) or (True, f"已开始抓取 {len(sids)} 部剧")
own = A.load_own()
assert len(own) == 54 and all(A.SID_RE.match(o["id"]) for o in own), len(own)
assert len({o["id"] for o in own}) == 54, "ID 重复"
c = A.app.test_client()
html = c.get("/admin").get_data(as_text=True)
assert "自家剧清单" in html and own[0]["id"] in html and "已添加" not in html
first = own[0]["id"]
r = c.post("/admin/add_own", data={"sid": first}, follow_redirects=True).get_data(as_text=True)
assert "已添加 1 部剧" in r and calls[-1] == [first], r[:200]
s = A.db.get_series(first)
assert s["grp"] == f"自家-{own[0]['region']}" and s["notes"] == own[0]["account"] and s["title"] == own[0]["title"], dict(s)
A.db.set_series_fields(first, grp="改过的组")                      # 模拟用户改过分组
r = c.post("/admin/add_own", data={"sid": "all"}, follow_redirects=True).get_data(as_text=True)
assert "已添加 53 部剧" in r and len(calls[-1]) == 53 and first not in calls[-1], r[:200]
assert A.db.get_series(first)["grp"] == "改过的组", "重复添加不能覆盖已有分组"
assert len(A.db.list_series(include_archived=True)) == 54
html = c.get("/admin").get_data(as_text=True)
assert html.count("已添加") == 54 and "没有新增" not in html
r = c.post("/admin/add_own", data={"sid": "all"}, follow_redirects=True).get_data(as_text=True)
assert "没有新增" in r
print("test_own OK")
