#!/usr/bin/env python3
"""ja_quality_ci.py — Zenn自動投稿CI用の日本語品質チェック（warn-only・fail-open）

publish.ymlの公開直前に実行し、層3（ja_quality/MiniMax-M3）の指摘を
GitHub Step Summaryへ警告注記する。**投稿は止めない**（常にexit 0）。
- slug抽出失敗・API鍵不在・LLM応答異常・例外のいずれも「警告+スキップ」で扱う
- Phase 0拡張（2026-09-25・ふくけい承認）: 発火マトリクス「Zenn公開=層1+層3」の自動化
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def build_lines() -> list[str]:
    """要約行リストを返す（例外を含む全失敗をwarn文字列に変換・投げない）。"""
    lines: list[str] = []
    try:
        from publisher import extract_slug, get_issue_body

        slug = extract_slug(get_issue_body(
            os.environ.get("GITHUB_TOKEN", ""),
            os.environ.get("GITHUB_REPOSITORY", ""),
            int(os.environ.get("ISSUE_NUMBER", "0")),
        ))
        if not slug:
            return ["⚠️ slug抽出失敗 → 日本語品質チェックをスキップ"]

        from generator import MINIMAX_BASE_URL
        from ja_quality import check_file
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ.get("MINIMAX_API_KEY", ""),
            base_url=MINIMAX_BASE_URL,
        )
        issues = check_file(client, f"articles/{slug}.md")
        if issues is None:
            lines.append("⚠️ 日本語品質: 点検不能（LLM応答解析失敗）→ 投稿は継続")
        elif issues:
            lines.append(f"⚠️ **日本語品質の指摘 {len(issues)}件** → 投稿は継続（公開後に修正検討）")
            for it in issues:
                lines.append(
                    f"- {str(it.get('problem', ''))[:80]} ／ 該当: `{str(it.get('quote', ''))[:40]}`"
                    f" ／ 修正案: {str(it.get('suggestion', ''))[:60]}")
        else:
            lines.append("✅ 日本語品質OK（指摘0件）")
    except Exception as e:  # noqa: BLE001 — fail-open契約: 全例外を警告文字列化
        lines.append(
            f"⚠️ 日本語品質チェック自体が失敗 → 投稿は継続: "
            f"{type(e).__name__}: {e}"[:200])
    return lines


def main() -> int:
    lines = build_lines()
    text = "## 📝 日本語品質チェック（warn-only）\n\n" + "\n".join(
        f"- {ln}" if not ln.startswith(("✅", "⚠️")) else ln for ln in lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    return 0  # 常に成功（warn-only契約・blockしない）


if __name__ == "__main__":
    sys.exit(main())
