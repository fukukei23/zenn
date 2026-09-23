#!/usr/bin/env python3
"""bundler.py — C級単発記事の群化ジェネレータ（spec: docs/superpowers/specs/2026-09-23_Zenn記事選題大枠化-design.md §4-4）

下書きの単発実装型記事をテーマ語で束ね、まとめ記事の目次案を生成する。
LLM呼出なし・決定的（テスト可能）。目次案の本文化は人間 or 手動実行。
"""
from __future__ import annotations

import re

# テーマ語の決定的抽出（タイトル・タグから）
THEME_WORDS = ["pytest", "Claude Code", "python", "セキュリティ", "NexusCore",
               "Claude Code hook", "CLI", "CI/CD", "Docker", "GAS", "Zenn",
               "SSOT", "cron", "SSR", "playwright", "AWS", "GCP"]
# 短い語（より広いテーマ）を先にマッチ: hook記事も"Claude Code"テーマに束ねる（群化の意図）
_THEME_PATTERNS = [(w, re.compile(re.escape(w), re.IGNORECASE))
                   for w in sorted(THEME_WORDS, key=len)]


def extract_theme(title: str, tags: list) -> str:
    """タイトル・タグからテーマ語を決定的に抽出する。

    複数ヒット時はより短い（より広い）テーマ語を優先する
    （hook記事も"Claude Code"テーマに束ねるのが群化の意図・MLR r1でdocstring矛盾を修正）。
    """
    text = f"{title} {' '.join(tags)}"
    for w, pat in _THEME_PATTERNS:
        if pat.search(text):
            return w.lower().replace(" ", "-")
    if tags:
        return tags[0].lower()
    return "unknown"


def group_by_theme(articles: list) -> dict:
    """記事リストをテーマ語でグルーピングする。"""
    groups: dict = {}
    for a in articles:
        theme = extract_theme(a.get("title", ""), a.get("tags", []))
        groups.setdefault(theme, []).append(a)
    return groups


def bundle_proposals(groups: dict, min_size: int = 3) -> list:
    """3本以上の群からまとめ記事の目次案を生成する。

    戻り値: [{"theme", "title", "chapters": [{"chapter", "files"}]}]
    """
    proposals = []
    for theme, arts in sorted(groups.items()):
        if len(arts) < min_size:
            continue
        chapters = [
            {"chapter": f"{i + 1}. {a['title']}", "files": [a["file"]]}
            for i, a in enumerate(arts)
        ]
        title = f"【まとめ】{theme}で学ぶ実践ノウハウ {len(arts)}選"
        proposals.append({
            "theme": theme,
            "title": title,
            "chapters": chapters,
        })
    return proposals