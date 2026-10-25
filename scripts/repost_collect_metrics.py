#!/usr/bin/env python3
"""転載ドリップ効果測定: note/Zennの記事別数値を収集してmetrics.jsonlに追記する。

使い方: python3 repost_collect_metrics.py [--note-only] [--zenn-only]
出力: ~/projects/zenn/repost-metrics/metrics.jsonl（append only）
終了コード: 0=両方成功 / 1=片方失敗 / 2=両方失敗
データは日次で1行=1日×1記事・失敗時はその日の行を書かない（欠損扱い）。
spec: docs/superpowers/specs/2026-10-25-転載ドリップ効果測定ループ-design.md
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

NOTE_PROFILE = "/home/yn4416/.cache/ms-playwright-note-f9ec"
ZENN_PROFILE = "/home/yn4416/.cache/ms-playwright-zenn-metrics"
OUT = Path.home() / "projects" / "zenn" / "repost-metrics" / "metrics.jsonl"
JST = timezone(timedelta(hours=9))


def note_collect(page) -> list[dict]:
    """noteダッシュボードの記事別テーブル（ビュー/スキ/コメント）を取得する。"""
    page.goto("https://note.com/dashboard", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    for _ in range(10):
        page.keyboard.press("End")
        page.wait_for_timeout(1200)
    page.wait_for_timeout(2000)
    rows = page.evaluate(
        """() => {
      const out = [];
      for (const a of document.querySelectorAll('a[href*="/n/"]')) {
        const href = a.getAttribute('href') || '';
        const m = href.match(/\\/n\\/([a-z0-9]+)/);
        if (!m || !href.includes('fukukei23')) continue;
        const title = (a.textContent || '').trim().slice(0, 60);
        let el = a;
        let nums = [];
        for (let i = 0; i < 5 && el; i++) {
          nums = [...new Set([...el.querySelectorAll('*')]
            .map(e => (e.textContent || '').trim())
            .filter(t => /^[0-9,]{1,8}$/.test(t)))];
          if (nums.length >= 1) break;
          el = el.parentElement;
        }
        const n = (s) => parseInt(s.replace(/,/g, ''), 10);
        out.push({
          note_id: m[1],
          title,
          views: nums.length >= 1 ? n(nums[0]) : null,
          likes: nums.length >= 2 ? n(nums[1]) : null,
          comments: nums.length >= 3 ? n(nums[2]) : null,
        });
      }
      return out;
    }"""
    )
    return rows


def zenn_collect(page) -> list[dict]:
    """Zenn統計ダッシュボードの記事別ビュー数（N回）を取得する。"""
    page.goto("https://zenn.dev/dashboard/stats", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    # 「もっと読み込む」が消えるまで展開（上限20回・防御）
    for _ in range(20):
        btn = page.locator('button:has-text("もっと読み込む")')
        if btn.count() == 0:
            break
        btn.first.click()
        page.wait_for_timeout(2000)
    rows = page.evaluate(
        """() => {
      const out = [];
      for (const a of document.querySelectorAll('a[href^="/"][class*="Link"], a[href*="/articles/"], a[href]')) {
        const href = a.getAttribute('href') || '';
        if (!href.includes('/articles/')) continue;
        const slug = href.split('/articles/')[1].split('/')[0].split('?')[0];
        if (!slug) continue;
        const container = a.closest('div[class*="container"], li, article') || a.parentElement;
        const text = container ? container.textContent || '' : '';
        const mv = text.match(/([0-9,]+)\\s*回/);
        const title = (a.textContent || '').trim().slice(0, 60);
        if (!mv) continue;
        out.push({
          slug,
          title,
          views: parseInt(mv[1].replace(/,/g, ''), 10),
        });
      }
      const seen = new Set();
      return out.filter(r => !seen.has(r.slug) && seen.add(r.slug));
    }"""
    )
    return rows


def append_rows(platform: str, rows: list[dict]) -> int:
    """metrics.jsonl に追記する（同一date+同一記事の重複行は書かない）。"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                r = json.loads(line)
                key = (r.get("date"), r.get("platform"), r.get("note_id") or r.get("slug"))
                existing.add(key)
            except json.JSONDecodeError:
                continue
    written = 0
    with OUT.open("a") as f:
        for r in rows:
            key = (today, platform, r.get("note_id") or r.get("slug"))
            if key in existing:
                continue
            rec = {"date": today, "platform": platform, **r}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--note-only", action="store_true")
    ap.add_argument("--zenn-only", action="store_true")
    args = ap.parse_args()

    results = {}
    with sync_playwright() as p:
        if not args.zenn_only:
            try:
                ctx = p.chromium.launch_persistent_context(
                    NOTE_PROFILE, headless=True, viewport={"width": 1280, "height": 1000}
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                results["note"] = note_collect(page)
                ctx.close()
            except Exception as e:
                print(f"note収集失敗: {e}", file=sys.stderr)
                results["note"] = None
        if not args.note_only:
            try:
                ctx = p.chromium.launch_persistent_context(
                    ZENN_PROFILE, headless=True, viewport={"width": 1280, "height": 1000}
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                results["zenn"] = zenn_collect(page)
                ctx.close()
            except Exception as e:
                print(f"zenn収集失敗: {e}", file=sys.stderr)
                results["zenn"] = None

    written = 0
    for platform, rows in results.items():
        if rows is None:
            continue
        n = append_rows(platform, rows)
        written += n
        print(f"{platform}: {len(rows)}件取得・{n}行追記")

    failed = [k for k, v in results.items() if v is None]
    if len(failed) == 2:
        print("両プラットフォームとも失敗", file=sys.stderr)
        return 2
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
