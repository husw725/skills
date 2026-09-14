#!/usr/bin/env python3
"""把 pipeline 产物 (storyboard.json + script.md) 渲染成单文件黑金风格 HTML 报告。

用法: python3 scripts/render_report.py output/ep101 --title "Bloodsuckers Ep.101"
产出: <workdir>/report.html (自包含, 内嵌若干关键帧缩略图)
"""
import argparse
import base64
import json
import re
from pathlib import Path

import markdown

N_GALLERY = 10  # 内嵌关键帧数量

CSS = """
:root { --bg:#0c0c0e; --panel:#141416; --line:#2a2a2e; --gold:#d4af37; --gold-dim:#9a7b1f;
        --text:#e8e6e0; --muted:#9a978f; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:"Songti SC","Noto Serif SC",Georgia,serif;
       line-height:1.7; padding:0 0 80px; }
.wrap { max-width:1200px; margin:0 auto; padding:0 24px; }
header { padding:64px 0 40px; text-align:center;
         background:radial-gradient(ellipse 70% 100% at 50% 0%, #1c1a12 0%, var(--bg) 70%); }
header h1 { font-size:2.6rem; letter-spacing:.12em; color:var(--gold);
            text-shadow:0 0 24px rgba(212,175,55,.25); font-weight:600; }
header .sub { color:var(--muted); margin-top:10px; letter-spacing:.3em; font-size:.85rem; }
header .rule { width:120px; height:1px; margin:26px auto 0;
               background:linear-gradient(90deg, transparent, var(--gold), transparent); }
.kpis { display:flex; flex-wrap:wrap; gap:14px; justify-content:center; margin:36px 0 10px; }
.kpi { background:var(--panel); border:1px solid var(--line); border-top:2px solid var(--gold-dim);
       padding:16px 28px; min-width:130px; text-align:center; }
.kpi b { display:block; font-size:1.7rem; color:var(--gold); font-weight:600; }
.kpi span { color:var(--muted); font-size:.8rem; letter-spacing:.15em; }
h2.sec { margin:64px 0 18px; font-size:1.35rem; color:var(--gold); letter-spacing:.18em;
         border-left:3px solid var(--gold); padding-left:14px; font-weight:600; }
.gallery { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }
.gallery figure { background:var(--panel); border:1px solid var(--line); }
.gallery img { width:100%; display:block; }
.gallery figcaption { padding:6px 10px; font-size:.75rem; color:var(--muted); }
.md { background:var(--panel); border:1px solid var(--line); padding:32px 36px; }
.md h1 { font-size:1.5rem; color:var(--gold); margin:.4em 0 .8em; }
.md h2 { font-size:1.12rem; color:var(--gold); margin:1.6em 0 .6em;
         border-bottom:1px solid var(--line); padding-bottom:.3em; }
.md p, .md li { margin:.5em 0; }
.md blockquote { color:var(--muted); border-left:3px solid var(--gold-dim); padding-left:14px; margin:.8em 0; }
.md strong { color:var(--gold); }
table { border-collapse:collapse; width:100%; font-size:.85rem;
        font-family:"PingFang SC","Noto Sans SC",sans-serif; }
th { background:#1b1912; color:var(--gold); padding:8px 10px; text-align:left;
     border:1px solid var(--line); position:sticky; top:0; white-space:nowrap; }
td { border:1px solid var(--line); padding:7px 10px; vertical-align:top; }
tr:nth-child(even) td { background:#121214; }
.tablebox { max-height:75vh; overflow:auto; border:1px solid var(--line); }
.md table td, .md table th { font-size:.88rem; }
footer { text-align:center; color:var(--muted); font-size:.75rem; margin-top:70px; letter-spacing:.1em; }
"""


def img_b64(p: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--title", default="素材前置处理报告")
    args = ap.parse_args()
    wd = Path(args.workdir)

    board = json.loads((wd / "storyboard.json").read_text())
    script_md = (wd / "script.md").read_text()
    transcript = json.loads((wd / "transcript.json").read_text())

    total_sec = board[-1]["timecode"].split("-")[1]
    n_scenes = len(re.findall(r"^## 第", script_md, re.M))
    chars = set()
    for r in board:
        for c in re.split(r"[;；]", r["characters"]):
            code = re.split(r"[（(]", c.strip())[0].strip()
            if code and code != "无人物":
                chars.add(code)

    kpis = [(len(board), "镜头"), (n_scenes, "场次"), (len(transcript), "台词行"),
            (len(chars), "人物代号"), (total_sec, "片长")]
    kpi_html = "".join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for v, k in kpis)

    # 均匀抽 N 张关键帧
    frames_dir = wd / "frames"
    idxs = [board[round(i * (len(board) - 1) / (N_GALLERY - 1))]["shot_id"] for i in range(N_GALLERY)]
    gallery = ""
    for sid in idxs:
        p = frames_dir / f"shot{sid:04d}_1.jpg"
        if p.exists():
            row = next(r for r in board if r["shot_id"] == sid)
            gallery += (f'<figure><img src="{img_b64(p)}" loading="lazy">'
                        f'<figcaption>镜{sid} · {row["timecode"].split("-")[0]} · {row["scene"]}</figcaption></figure>')

    script_html = markdown.markdown(script_md, extensions=["tables"])

    headers = ["镜号", "时间码", "时长", "景别", "运镜", "场景", "人物", "动作", "情绪", "台词"]
    keys = ["shot_id", "timecode", "duration", "shot_size", "camera_move",
            "scene", "characters", "action", "mood", "dialogue"]
    rows = "".join("<tr>" + "".join(f"<td>{r[k]}</td>" for k in keys) + "</tr>" for r in board)
    board_html = (f'<div class="tablebox"><table><thead><tr>'
                  + "".join(f"<th>{h}</th>" for h in headers)
                  + f"</tr></thead><tbody>{rows}</tbody></table></div>")

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{args.title}</title><style>{CSS}</style></head><body>
<header><div class="wrap"><h1>{args.title}</h1>
<div class="sub">素材前置处理 · 原片分镜表 &amp; 反向剧本</div><div class="rule"></div>
<div class="kpis">{kpi_html}</div></div></header>
<div class="wrap">
<h2 class="sec">关键帧速览</h2><div class="gallery">{gallery}</div>
<h2 class="sec">反向剧本</h2><div class="md">{script_html}</div>
<h2 class="sec">原片分镜表（{len(board)} 镜）</h2>{board_html}
<footer>video_redraw pipeline · 自动生成</footer>
</div></body></html>"""

    out = wd / "report.html"
    out.write_text(html)
    print(f"{out}  ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
