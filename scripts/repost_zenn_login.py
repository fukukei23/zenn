#!/usr/bin/env python3
"""Zennログイン用: 専用プロファイルでheadedブラウザを開き、ログイン完了を待って閉じる。

使い方: python3 repost_zenn_login.py [timeout_sec]
ログイン検出: https://zenn.dev/dashboard へのアクセスが記事の管理ページとして
表示されればログイン済み（未ログインではサインイン導線へ飛ぶ）。
note版（repost_note_login.py）と同じ persistent profile 方式。
"""
import sys

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

PROFILE = "/home/yn4416/.cache/ms-playwright-zenn-metrics"
TIMEOUT = int(sys.argv[1]) if len(sys.argv) > 1 else 900


def is_logged_in(page) -> bool:
    """ダッシュボードが「記事の管理」として出ればログイン済み。"""
    try:
        page.goto("https://zenn.dev/dashboard", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)
        title = page.title()
        return "記事の管理" in title and "/signin" not in page.url
    except Exception:
        return False


def main() -> int:
    # Cloudflare ボット検知対策: playwright-stealth（自作PyPI版・pw-stealth-enhanced記事）を適用
    with Stealth().use_sync(sync_playwright()) as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if is_logged_in(page):
            print("すでにログイン済みです")
            ctx.close()
            return 0
        page.goto("https://zenn.dev/signin", wait_until="domcontentloaded")
        print("ブラウザで zenn.dev にログインしてください（このウィンドウで操作）")
        for _ in range(TIMEOUT // 5):
            page.wait_for_timeout(5000)
            if is_logged_in(page):
                print("ログインを検出しました")
                ctx.close()
                return 0
        print("タイムアウト: ログインが完了しませんでした")
        ctx.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
