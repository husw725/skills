#!/usr/bin/env python3
"""把 output/screenplay/ep1XX.fountain 合订成全季剧本: .fountain 源文件 + Courier 排版 HTML 阅读版。"""
import re
import sys
from pathlib import Path

SP = Path("output/screenplay")
EPS = [f"ep1{i:02d}" for i in range(1, 11)]

TITLE_PAGE = """\
Title: BLOODSUCKERS
Credit: Season One — Complete Teleplay
Author: Reverse-engineered from broadcast footage (video_redraw pipeline)
Notes: Dialogue transcribed from original audio; action reconstructed from per-shot analysis.
Draft date: 2026-08-13

===

"""

def lint(name: str, text: str) -> list[str]:
    problems = []
    if re.search(r"[一-鿿]", text):
        problems.append(f"{name}: 残留中文字符")
    if f"END OF EPISODE" not in text and "END OF SEASON" not in text:
        problems.append(f"{name}: 缺少结尾标记")
    if not re.search(r"^(INT|EXT)", text, re.M):
        problems.append(f"{name}: 无 slugline")
    return problems

def main():
    parts, problems, total_lines = [], [], 0
    for ep in EPS:
        p = SP / f"{ep}.fountain"
        if not p.exists():
            sys.exit(f"缺少 {p}")
        t = p.read_text().strip() + "\n"
        problems += lint(ep, t)
        total_lines += t.count("\n")
        parts.append(t)
    if problems:
        print("格式问题:", *problems, sep="\n  ")
    full = TITLE_PAGE + "\n\n".join(parts)
    out = SP / "BLOODSUCKERS_S01_full.fountain"
    out.write_text(full)

    # Courier 阅读版 HTML: fountain 轻排版(标题页/居中人物cue/动作行), 黑金封面与报告一致
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body_lines = []
    for ln in full.splitlines():
        s, e = ln.strip(), esc(ln)
        if re.match(r"^(INT|EXT|EST|I/E)[. /]", s):
            body_lines.append(f'<div class="slug">{esc(s)}</div>')
        elif re.match(r"^EPISODE \d+", s):
            body_lines.append(f'<div class="ep">{esc(s)}</div>')
        elif s.isupper() and 0 < len(s) <= 40 and not s.startswith(("FADE", "CUT", "END", "===")) \
                and not re.match(r"^(INT|EXT)", s):
            body_lines.append(f'<div class="cue">{esc(s)}</div>')
        elif s.startswith("(") and s.endswith(")"):
            body_lines.append(f'<div class="paren">{esc(s)}</div>')
        elif s in ("FADE IN:", "FADE TO BLACK.") or s.endswith("TO:") or s.startswith("END OF"):
            body_lines.append(f'<div class="trans">{esc(s)}</div>')
        else:
            body_lines.append(f'<div class="act">{e or "&nbsp;"}</div>')
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BLOODSUCKERS — Season One Teleplay</title><style>
body{{background:#0c0c0e;margin:0;padding:40px 0;font-family:'Courier New',Courier,monospace}}
.page{{max-width:620px;margin:0 auto;background:#f7f5f0;color:#1a1a1a;padding:60px 70px;
line-height:1.25;font-size:14px}}
.cover{{text-align:center;padding:120px 70px}}
.cover h1{{letter-spacing:.3em;font-size:28px}}
.cover p{{color:#555}}
.ep{{font-weight:bold;text-align:center;margin:48px 0 16px;letter-spacing:.1em}}
.slug{{font-weight:bold;margin:20px 0 8px}}
.cue{{margin:12px 0 0 180px}}
.paren{{margin:0 0 0 140px;color:#333}}
.act{{margin:6px 0;white-space:pre-wrap}}
.trans{{text-align:right;margin:14px 0;font-weight:bold}}
.cover,.page{{box-shadow:0 0 30px rgba(212,175,55,.08)}}
</style></head><body>
<div class="page cover"><h1>BLOODSUCKERS</h1><p>Season One — Complete Teleplay<br>
Episodes 101–110 · ~{total_lines // 55} pages<br><br>
Reverse-engineered from broadcast footage<br>video_redraw pipeline · 2026</p></div>
<div class="page">{"".join(body_lines)}</div></body></html>"""
    (SP / "BLOODSUCKERS_S01_full.html").write_text(html)
    print(f"OK: {out} ({total_lines} 行 ≈ {total_lines // 55} 页) + 阅读版 HTML")

if __name__ == "__main__":
    main()
