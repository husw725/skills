"""起一个带假数据的演示服务，用来看页面效果。不联网、不花钱。
运行：python tests/seed_demo.py   → http://127.0.0.1:8765/
"""
import os
import pathlib
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="apify_helper_demo_")
os.environ["APIFY_HELPER_DB"] = os.path.join(TMP, "demo.sqlite")
os.environ["APIFY_HELPER_CONFIG"] = os.path.join(TMP, "config.json")
pathlib.Path(os.environ["APIFY_HELPER_CONFIG"]).write_text('{"apify_token": "test-token", "schedule_enabled": false}', "utf-8")

import app as A  # noqa: E402
from test_smoke import SID_A, SID_B, SID_C, fake_run_factory  # noqa: E402

for sid, grp in ((SID_A, "自家"), (SID_B, "竞品"), (SID_C, "自家")):
    A.db.add_series(sid, grp)
DAYS = ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")
for day, scale in zip(DAYS, (1.0, 1.12, 1.21, 1.27, 1.31)):
    A.apify_client.run = fake_run_factory(scale)
    A.run_job([SID_A, SID_B, SID_C], "schedule", taken_at=f"{day} 09:00:00")
A.db.set_series_fields(SID_A, notes="S1 主推")
A.db.set_series_fields(SID_C, status="error", status_msg="本次未抓到数据：检查剧 ID")
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"demo → http://127.0.0.1:{port}/")
    A.app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
