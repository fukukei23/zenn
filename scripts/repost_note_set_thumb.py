#!/usr/bin/env python3
"""公開済みnote記事への見出し画像（サムネ）設定。

実測フロー（2026-10-12）:
  エディタ上部中央の濃い円形ボタン（約509,121・位置特定）→メニュー「画像をアップロード」
  →ファイルチューザー→切り取りモーダル「保存」→記事ページのバナー消滅で成功判定。

使い方: python3 repost_note_set_thumb.py <note_id> <thumb.png>

2026-10-13修正（サムネ無し投稿事故の根本原因4点）:
  ①検証を「エディタ上のカバー画像実在」へ変更（旧バナー確認は伝播遅延で常に偽陰性・
    og:imageポーリングは再生成過渡期に偽陽性・両方実測で棄却）
  ②ボタン検出にフォールバック追加（固定座標窓x470-560/y85-160はツールチップ等で
    レイアウトがずれると未検出exit 2・実測。フォールバック=ProseMirror上部の
    32-56px角・無テキストボタンを領域ベースで選択）
  ③保存クリックはモーダル内ボタンへのJS直接クリック（CropModal__overlayが
    ポインタを遮蔽しPlaywrightクリックが空振りする実測のため）+5秒ロード待ち
  ④staged残留カバーの×除去を開始時に実施（前回失敗の残留が次回を妨害する実測）
"""
import re
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
NOTE_ID_RE = re.compile(r"^n[0-9a-f]+$")


def log(msg: str) -> None:
    print(f"[set-thumb {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    note_id = sys.argv[1]
    thumb = sys.argv[2]
    # 単体実行ガード（2026-10-13 MLR採用: drip側と同じ正規表現で
    # 引数検証し空/不正IDで他記事への誤適用を防ぐ）
    if not NOTE_ID_RE.fullmatch(note_id):
        log(f"note_id形式不正（{note_id!r}）→ exit 2")
        return 2
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False, viewport={"width": 1280, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://editor.note.com/notes/{note_id}/edit/",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('div.ProseMirror[contenteditable="true"]', timeout=30000)
        page.wait_for_timeout(4000)
        # 前回実行のstaged残留カバー（未保存含む・×ボタンは右側32px角）を除去してから開始
        # （2026-10-13実測: 保存クリック失敗で画像がstaged残留し次回のボタン検出を妨害する）
        removed = page.evaluate("""() => {
          const pm = document.querySelector('div.ProseMirror[contenteditable="true"]');
          if (!pm) return false;
          const pmTop = pm.getBoundingClientRect().top;
          for (const b of document.querySelectorAll('button')) {
            const r = b.getBoundingClientRect();
            if (r.width < 28 || r.width > 60 || r.height < 28 || r.height > 60) continue;
            if ((b.innerText || '').trim() !== '') continue;
            if (r.y < 40 || r.y > pmTop) continue;
            if (r.x > 800) {  // カバー領域右端の×（削除）ボタン
              b.click();
              return true;
            }
          }
          return false;
        }""")
        if removed:
            log("staged残留カバーを検出→×で除去してやり直し")
            page.wait_for_timeout(2000)
        target = page.evaluate("""() => {
          // 1) 従来の固定座標窓（クリーンなレイアウトでは約509,121に実在）
          for (const b of document.querySelectorAll('button')) {
            const r = b.getBoundingClientRect();
            if (r.x > 470 && r.x < 560 && r.y > 85 && r.y < 160 && r.width > 30) {
              return {x: r.x + r.width/2, y: r.y + r.height/2, how: "fixed-window"};
            }
          }
          // 2) フォールバック: ProseMirror上部のカバー領域ボタン（32-56px角・無テキスト）
          const pm = document.querySelector('div.ProseMirror[contenteditable="true"]');
          if (!pm) return null;
          const pmTop = pm.getBoundingClientRect().top;
          let best = null;
          for (const b of document.querySelectorAll('button')) {
            const r = b.getBoundingClientRect();
            if (r.width < 28 || r.width > 60 || r.height < 28 || r.height > 60) continue;
            if ((b.innerText || '').trim() !== '') continue;
            if (r.y < 40 || r.y > pmTop) continue;  // カバー領域=ヘッダバー下〜本文上
            if (!best || r.y < best.y) best = r;
          }
          if (best) return {x: best.x + best.width/2, y: best.y + best.height/2, how: "fallback-area"};
          return null;
        }""")
        if not target:
            log("カバー画像ボタンが見つからず（exit 2・座標窓+領域フォールバック両方）")
            ctx.close()
            return 2
        log(f"ボタン検出: {target['how']} ({target['x']:.0f},{target['y']:.0f})")
        page.mouse.click(target["x"], target["y"])
        page.wait_for_timeout(2000)
        with page.expect_file_chooser(timeout=15000) as fc_info:
            page.locator('text=画像をアップロード').first.click()
        fc_info.value.set_files(thumb)
        log(f"ファイル設定: {thumb}")
        # 切り取りモーダルの出現を待ってから保存（旧: 固定6秒待ちのみ）
        page.wait_for_selector('div[class*="CropModal"]', timeout=20000)
        # モーダル内クロップ画像のロード待ち（2026-10-13実測: 直後クリックだと
        # 保存が空振りする・5秒待ちで成功実測）
        page.wait_for_timeout(5000)
        # 保存クリックはモーダル内ボタンへのJS直接クリック（2026-10-13実測:
        # CropModal__overlayがポインタを遮蔽し Playwright クリックが空振りする
        # 場合があるため DOM click を優先・失敗時はPlaywrightにフォールバック）
        saved = page.evaluate("""() => {
          const modal = document.querySelector('div[class*="CropModal"]');
          if (!modal) return 'no-modal';
          for (const b of modal.querySelectorAll('button')) {
            if ((b.innerText || '').includes('保存')) {
              if (b.disabled) return 'disabled';
              b.click();
              return 'clicked';
            }
          }
          return 'no-save-btn';
        }""")
        if saved != "clicked":
            log(f"モーダル内JS保存失敗（{saved}）→ Playwrightクリックへフォールバック")
            page.locator('div[class*="CropModal"] button:has-text("保存")').first.click(
                timeout=15000
            )
        log("切り取りモーダル保存クリック")

        # 検証: エディタ上のカバー画像実在（2026-10-13実測: og:imageは再生成の
        # 過渡期に偽陽性（一瞬uploads→文字カードへ戻る）を出すため gate には使わない。
        # エディタのカバー領域に100px超のimgが出現=適用確定）
        applied = False
        for i in range(1, 7):  # 5秒 x 6 = 最大30秒
            page.wait_for_timeout(5000)
            has_cover = page.evaluate("""() => {
              const pm = document.querySelector('div.ProseMirror[contenteditable="true"]');
              if (!pm) return false;
              const pmTop = pm.getBoundingClientRect().top;
              for (const img of document.querySelectorAll('img')) {
                const r = img.getBoundingClientRect();
                if (r.y >= 40 && r.y < pmTop && r.width > 100) return true;
              }
              return false;
            }""")
            if has_cover:
                applied = True
                log(f"検証: エディタにカバー画像 出現（{i*5}秒後）→ 成功")
                break
            log(f"検証: カバー画像 未出現（{i*5}/30秒）")
        page.screenshot(path="/tmp/set-thumb-result.png")
        ctx.close()
        return 0 if applied else 1


if __name__ == "__main__":
    sys.exit(main())
