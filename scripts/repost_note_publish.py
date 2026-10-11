#!/usr/bin/env python3
"""note下書きの公開専用スクリプト（既存下書きURLを開いて公開に進む→公開する）。

使い方: python3 repost_note_publish.py <draft_url> [timeout_sec=600]
GOファイル（/tmp/note-publish-go）が存在する場合のみ公開操作を実行する（誤発火防止）。
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
GO_FILE = Path(os.environ.get("NOTE_GO_FILE", "/tmp/note-publish-go"))


def log(msg: str) -> None:
    print(f"[note-pub {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    draft_url = sys.argv[1]
    timeout_sec = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    if not GO_FILE.exists():
        log(f"GOファイル({GO_FILE})が無いため中止（誤発火防止・exit 3）")
        return 3
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(timeout_sec * 1000)
        page.goto(draft_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('div.ProseMirror[contenteditable="true"]', timeout=30000)
        page.wait_for_timeout(3000)
        log(f"下書きを開きました: {page.url}")
        page.locator("text=公開に進む").first.click()
        page.wait_for_timeout(5000)
        page.screenshot(path="/tmp/note-publish-step1.png")
        log(f"公開設定画面へ（URL: {page.url}）")
        # ハッシュタグ追加（発見性向上・2026-10-11実測: デフォルトは空）
        HASHTAGS = ["AI", "VibeCoding"]
        try:
            hloc = page.locator('input[placeholder*="ハッシュタグ"]').first
            for tag in HASHTAGS:
                hloc.click()
                hloc.fill(tag)
                page.keyboard.press("Enter")
                page.wait_for_timeout(800)
                log(f"ハッシュタグ追加: {tag}")
        except Exception as e:
            log(f"ハッシュタグ追加失敗（継続）: {type(e).__name__}")
        # 最終ボタンは「投稿する」（公開するではない・2026-10-11実測）
        try:
            page.get_by_text("投稿する", exact=True).first.click(timeout=20000)
            log("投稿するボタンクリック完了")
        except Exception as e:
            log(f"投稿するボタン失敗: {type(e).__name__}（/tmp/note-publish-step1.png確認）")
            ctx.close()
            return 1
        page.wait_for_timeout(6000)
        page.screenshot(path="/tmp/note-final.png")
        log(f"最終URL: {page.url}")
        ctx.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
