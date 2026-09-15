#!/usr/bin/env python3
"""把逐集 Fountain 剧本合订成全季: .fountain 源文件 + Courier 排版 HTML 阅读版。

默认(不带参数)沿用 Bloodsuckers: output/screenplay/ep101..ep110.fountain → BLOODSUCKERS_S01_full.*
通用: python3 scripts/assemble_screenplay.py --title "WAN YAO TU LU ZHUAN" --subtitle "Season One" \
          --out output/wytl_s1/WYTL_S01_full output/wytl_*/screenplay.fountain
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

SP = Path("output/screenplay")
LEGACY = [SP / f"ep1{i:02d}.fountain" for i in range(1, 11)]


def lint(name: str, text: str) -> list[str]:
    problems = []
    if re.search(r"[一-鿿]", text):
        problems.append(f"{name}: 残留中文字符")
    if "END OF EPISODE" not in text and "END OF SEASON" not in text:
        problems.append(f"{name}: 缺少结尾标记")
    if not re.search(r"^(INT|EXT)", text, re.M):
        problems.append(f"{name}: 无 slugline")
    return problems


def ep_key(p: Path):
    """按集号排序: ep101.fountain / wytl_007/screenplay.fountain 都能取到数字。"""
    m = re.findall(r"\d+", p.parent.name if p.name == "screenplay.fountain" else p.stem)
    return int(m[-1]) if m else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="逐集 .fountain(默认 Bloodsuckers 10 集)")
    ap.add_argument("--title", default="BLOODSUCKERS")
    ap.add_argument("--subtitle", default="Season One — Complete Teleplay")
    ap.add_argument("--out", default=str(SP / "BLOODSUCKERS_S01_full"), help="输出前缀(不带扩展名)")
    args = ap.parse_args()
    files = sorted((Path(f) for f in args.files), key=ep_key) if args.files else LEGACY

    parts, problems, total_lines = [], [], 0
    for p in files:
        if not p.exists():
            sys.exit(f"缺少 {p}")
        t = p.read_text().strip() + "\n"
        problems += lint(p.parent.name if p.name == "screenplay.fountain" else p.stem, t)
        total_lines += t.count("\n")
        parts.append(t)
    if problems:
        print("格式问题:", *problems, sep="\n  ")
    title_page = (f"Title: {args.title}\nCredit: {args.subtitle}\n"
                  "Author: Reverse-engineered from footage (video_redraw pipeline)\n"
                  "Notes: Dialogue from original subtitles/audio; action reconstructed from footage analysis.\n"
                  f"Draft date: {dt.date.today():%Y-%m-%d}\n\n===\n\n")
    full = title_page + "\n\n".join(parts)
    out = Path(args.out + ".fountain")
    out.parent.mkdir(parents=True, exist_ok=True)
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
<title>{esc(args.title)} — {esc(args.subtitle)}</title><style>
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
<div class="page cover"><h1>{esc(args.title)}</h1><p>{esc(args.subtitle)}<br>
{len(files)} episodes · ~{total_lines // 55} pages<br><br>
Reverse-engineered from footage<br>video_redraw pipeline · {dt.date.today():%Y}</p></div>
<div class="page">{"".join(body_lines)}</div></body></html>"""
    Path(args.out + ".html").write_text(html)
    print(f"OK: {out} ({len(files)} 集, {total_lines} 行 ≈ {total_lines // 55} 页) + 阅读版 HTML")


if __name__ == "__main__":
    main()
