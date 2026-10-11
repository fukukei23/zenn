#!/usr/bin/env python3
"""公開済みnote記事への見出し画像（サムネ）設定。

実測フロー（2026-10-12）:
  エディタ上部中央の濃い円形ボタン（約509,121・位置特定）→メニュー「画像をアップロード」
  →ファイルチューザー→切り取りモーダル「保存」→記事ページのバナー消滅で成功判定。

使い方: python3 repost_note_set_thumb.py <note_id> <thumb.png>
"""
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"


def log(msg: str) -> None:
    print(f"[set-thumb {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    note_id = sys.argv[1]
    thumb = sys.argv[2]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://editor.note.com/notes/{note_id}/edit/",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('div.ProseMirror[contenteditable="true"]', timeout=30000)
        page.wait_for_timeout(4000)
        target = page.evaluate("""() => {
          for (const b of document.querySelectorAll('button')) {
            const r = b.getBoundingClientRect();
            if (r.x > 470 && r.x < 560 && r.y > 85 && r.y < 160 && r.width > 30) {
              return {x: r.x + r.width/2, y: r.y + r.height/2};
            }
          }
          return null;
        }""")
        if not target:
            log("カバー画像ボタンが見つからず（exit 2）")
            ctx.close()
            return 2
        page.mouse.click(target["x"], target["y"])
        page.wait_for_timeout(2000)
        with page.expect_file_chooser(timeout=15000) as fc_info:
            page.locator('text=画像をアップロード').first.click()
        fc_info.value.set_files(thumb)
        log(f"ファイル設定: {thumb}")
        page.wait_for_timeout(6000)
        page.get_by_role("button", name="保存").first.click(timeout=15000)
        log("切り取りモーダル保存クリック")
        page.wait_for_timeout(8000)
        # 検証: 記事ページのバナー消滅
        page2 = ctx.new_page()
        page2.goto(f"https://note.com/fukukei23/n/{note_id}",
                   wait_until="domcontentloaded", timeout=30000)
        page2.wait_for_timeout(6000)
        has_banner = page2.locator('text=見出し画像を設定してみませんか?').first.count() > 0
        log(f"検証: バナー残存={has_banner}（False=成功）")
        page2.screenshot(path="/tmp/set-thumb-result.png")
        ctx.close()
        return 0 if not has_banner else 1


if __name__ == "__main__":
    sys.exit(main())
