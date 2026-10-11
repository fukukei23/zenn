#!/usr/bin/env python3
"""note自動投稿（一体型・v2）: ログイン待ち→タイトル+本文（markdown貼り付け）→承認待ち→公開。

実測に基づく実装（2026-10-11）:
  - エディタは editor.note.com へ遷移・headlessでは空になるため headed 必須
  - タイトル: textarea[placeholder="記事タイトル"]
  - 本文: div.ProseMirror[contenteditable="true"] へクリップボード貼り付け（markdown完全変換実測済み）
フロー: ログイン待ち → 投入 → スクショ+要素集計 → /tmp/note-publish-go 待ち → 公開に進む → 公開する
使い方: python3 repost_note_post.py <note.mdのパス> [approve_wait_sec=1800]
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
GO_FILE = Path(os.environ.get("NOTE_GO_FILE", "/tmp/note-publish-go"))
SHOT_DIR = Path("/tmp")


def log(msg: str) -> None:
    print(f"[note-post {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def on_editor(page) -> bool:
    """編集ページに到達したか（URLに/loginが無い=ログイン済み）。"""
    try:
        page.goto("https://note.com/notes/new", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(4000)  # editor.note.comへの遷移待ち
        return "/login" not in page.url
    except Exception:
        return False


def main() -> int:
    md_path = Path(sys.argv[1])
    approve_wait = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    text = md_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    title = ""
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("# ") and not title:
            title = ln[2:].strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    log(f"原稿: {md_path.name} / タイトル: {title[:40]} / 本文{len(body)}文字")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://editor.note.com")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # --- フェーズ1: ログイン待ち ---
        page.goto("https://note.com/notes/new", wait_until="domcontentloaded")
        log("ブラウザ起動。ログイン済みならそのまま投入へ進みます")
        deadline = time.time() + 900
        logged = False
        while time.time() < deadline:
            if on_editor(page):
                logged = True
                break
            time.sleep(8)
        if not logged:
            log("タイムアウト: ログインされませんでした（exit 1）")
            ctx.close()
            return 1
        log(f"ログイン確認OK（URL: {page.url}）")

        # --- フェーズ2: エディタへの投入 ---
        page.wait_for_selector('div.ProseMirror[contenteditable="true"]', timeout=30000)
        page.wait_for_timeout(2000)

        # タイトル
        tloc = page.locator('textarea[placeholder="記事タイトル"]').first
        tloc.click()
        tloc.fill(title)
        log("タイトル投入OK")

        # 本文（クリップボード貼り付け・markdown変換）
        bloc = page.locator('div.ProseMirror[contenteditable="true"]').first
        bloc.click()
        page.evaluate("t => navigator.clipboard.writeText(t)", body)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(5000)
        counts = page.evaluate(
            """() => {
              const ed = document.querySelector('div.ProseMirror[contenteditable="true"]');
              return {
                chars: ed.innerText.length,
                h2: ed.querySelectorAll('h2').length,
                h3: ed.querySelectorAll('h3').length,
                li: ed.querySelectorAll('li').length,
                strong: ed.querySelectorAll('strong').length,
                pre: ed.querySelectorAll('pre').length,
                a: ed.querySelectorAll('a').length,
              };
            }"""
        )
        log(f"本文投入OK・変換集計: {counts}")
        shot1 = SHOT_DIR / "note-filled.png"
        page.screenshot(path=str(shot1), full_page=False)
        log(f"投入後スクショ: {shot1}")
        log(f"下書きURL: {page.url}")

        # --- フェーズ3: 承認待ち ---
        log(f"承認待ち: {GO_FILE} が作成されたら公開操作へ（最大{approve_wait}秒）")
        deadline = time.time() + approve_wait
        while time.time() < deadline:
            if GO_FILE.exists():
                break
            time.sleep(10)
        if not GO_FILE.exists():
            log("承認なしタイムアウト。下書き保存のまま終了（公開はしない）")
            ctx.close()
            return 2
        log("承認ファイル検出 → 公開操作")

        # --- フェーズ4: 公開操作 ---
        page.locator("text=公開に進む").first.click()
        page.wait_for_timeout(5000)
        page.screenshot(path=str(SHOT_DIR / "note-publish-step1.png"))
        log(f"公開設定画面へ（URL: {page.url}）")
        # 設定画面の「公開する」確認ボタン
        try:
            page.get_by_text("公開する", exact=True).first.click(timeout=15000)
            log("公開ボタンクリック完了")
        except Exception as e:
            log(f"公開ボタン失敗: {type(e).__name__}（スクショで確認して下さい）")
        page.wait_for_timeout(6000)
        page.screenshot(path=str(SHOT_DIR / "note-final.png"))
        log(f"最終URL: {page.url}")
        ctx.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
