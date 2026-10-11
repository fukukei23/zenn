#!/usr/bin/env python3
"""noteログインページを直接開いて待機（タブ2本方式・誤検出対策済み）。

page1: ログインページを表示し続ける（ふくけいの操作用・遷移させない）
page2: 15秒ごとに /notes/new を検査し「URLに/loginが無い+contenteditable要素あり」
       が2回連続で成立したらログイン確定としてブラウザを閉じる。
"""
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
TIMEOUT = int(sys.argv[1]) if len(sys.argv) > 1 else 1200


def editor_reachable(check_page) -> bool:
    """/notes/new が編集ページとして開ける（=ログイン済み）ことを厳密判定。"""
    try:
        check_page.goto("https://note.com/notes/new", wait_until="domcontentloaded", timeout=20000)
        check_page.wait_for_timeout(4000)
        if "/login" in check_page.url:
            return False
        return check_page.query_selector('[contenteditable="true"]') is not None
    except Exception:
        return False


def main() -> int:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        page1 = ctx.pages[0] if ctx.pages else ctx.new_page()
        page1.goto("https://note.com/login", wait_until="domcontentloaded")
        print(f"[note-wait] ログインページを表示しました（{TIMEOUT}秒待機・page1は操作用に保持）", flush=True)
        page2 = ctx.new_page()
        ok_count = 0
        deadline = time.time() + TIMEOUT
        ok = False
        while time.time() < deadline:
            if editor_reachable(page2):
                ok_count += 1
                if ok_count >= 2:
                    ok = True
                    break
            else:
                ok_count = 0
            time.sleep(15)
        print(f"[note-wait] ログイン確定判定: {ok}", flush=True)
        ctx.close()
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
