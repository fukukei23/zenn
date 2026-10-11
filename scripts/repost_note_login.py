#!/usr/bin/env python3
"""noteログイン用: 専用プロファイルでheadedブラウザを開き、ログイン完了を待って閉じる。

使い方: python3 repost_note_login.py [timeout_sec]
ログイン検出: https://note.com/mypage へのアクセスが /login へリダイレクトされなくなればOK。
"""
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
TIMEOUT = int(sys.argv[1]) if len(sys.argv) > 1 else 900


def is_logged_in(page) -> bool:
    """mypageへのアクセスがSPAリダイレクト後も/loginに飛ばされなければログイン済み。

    false positive対策（2026-10-11実測）: noteはクライアント側リダイレクトのため
    domcontentloaded直後のURL判定では未ログインでも/mypageに見える。
    → 3秒待ってからURLを2回連続確認+ログインページ要素が無いことを確認。
    """
    try:
        page.goto("https://note.com/mypage", wait_until="domcontentloaded", timeout=20000)
        for _ in range(2):
            page.wait_for_timeout(3000)
            if "/login" in page.url or "/mypage" not in page.url:
                return False
        return page.query_selector('[data-testid], header') is not None
    except Exception:
        return False


def main() -> int:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://note.com/login", wait_until="domcontentloaded")
        print("[note-login] ブラウザを開きました。ふくけいがログイン操作してください（最大{}秒待機）".format(TIMEOUT), flush=True)
        deadline = time.time() + TIMEOUT
        ok = False
        while time.time() < deadline:
            if is_logged_in(page):
                ok = True
                break
            time.sleep(10)
        print("[note-login] ログイン検出: {}".format(ok), flush=True)
        if ok:
            # セッションcookieをプロファイルへ保存させるため少し待ってから閉じる
            time.sleep(2)
        ctx.close()
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
