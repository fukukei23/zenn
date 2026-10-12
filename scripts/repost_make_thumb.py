#!/usr/bin/env python3
"""noteサムネイル合成（C型: AIイラスト背景+最小文字オーバーレイ）。

使い方: python3 repost_make_thumb.py <bg画像> <出力png> <tag文言> <copy文言>
出力は1280x720。パターン分析（20_PUBLISHING/noteサムネイルパターン分析.md）の
①型（絵主体・文字最小）をHTML→スクショで実装。
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{margin:0;width:1280px;height:720px;background:url('@@BG@@') center/cover;position:relative;font-family:"Hiragino Sans","Noto Sans JP",sans-serif}
.shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(15,23,42,0) 45%,rgba(15,23,42,.78) 100%)}
.tag{position:absolute;left:70px;bottom:150px;background:#fbbf24;color:#1c1917;font-weight:800;font-size:30px;padding:10px 30px;border-radius:999px}
.copy{position:absolute;left:70px;bottom:52px;color:#fff;font-size:54px;font-weight:900;text-shadow:0 2px 12px rgba(0,0,0,.5);max-width:1140px}
.author{position:absolute;right:60px;bottom:56px;color:rgba(255,255,255,.85);font-size:26px;font-weight:700}
</style></head><body>
<div class="shade"></div>
<span class="tag">{tag}</span>
<div class="copy">{copy}</div>
<span class="author">@fukukei23</span>
</body></html>"""


def main() -> int:
    bg, out, tag, copy = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    html = (TEMPLATE.replace("@@BG@@", Path(bg).resolve().as_uri())
            .replace("@@TAG@@", tag).replace("@@COPY@@", copy))
    html = html.replace("<span class=\"tag\">{tag}</span>", f'<span class="tag">{tag}</span>')
    html = html.replace("<div class=\"copy\">{copy}</div>", f'<div class="copy">{copy}</div>')
    html_path = Path(out).resolve().with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto(html_path.as_uri())
        page.wait_for_timeout(800)
        page.screenshot(path=str(Path(out).resolve()))
        b.close()
    print(f"[make-thumb] 生成: {out}（tag={tag} / copy={copy}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
