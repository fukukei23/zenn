#!/usr/bin/env python3
"""note投稿エディタの構造を実測するプローブ（書き込みなし・スクショ+要素情報出力のみ）。"""
import json

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
SHOT = "/tmp/note-editor-probe.png"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, viewport={"width": 1280, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://note.com/notes/new", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)
    print("URL:", page.url)
    print("TITLE:", page.title())
    # 入力候補要素の洗い出し
    info = page.evaluate(
        """() => {
      const out = [];
      for (const el of document.querySelectorAll('[contenteditable="true"], input[type="text"], textarea, h1, [placeholder]')) {
        out.push({
          tag: el.tagName,
          cls: (el.className || '').toString().slice(0, 80),
          ph: el.getAttribute('placeholder') || '',
          ce: el.getAttribute('contenteditable'),
          dataTestid: el.getAttribute('data-testid') || '',
        });
      }
      return out;
    }"""
    )
    print("ELEMENTS:", json.dumps(info, ensure_ascii=False, indent=1))
    page.screenshot(path=SHOT, full_page=False)
    print("SCREENSHOT:", SHOT)
    # ブラウザは開いたまま維持（後続fillが同じプロファイルを使うため閉じる）
    ctx.close()
