#!/usr/bin/env python3
"""theme_policy.py — 選題の型分類と配合強制（spec: docs/superpowers/specs/2026-09-23_Zenn記事選題大枠化-design.md §4-1）

LLMの提案を型分類（cross=横断テーマ・体験談型 / single=単発実装型）し、
配合（cross比率7割目標）を機械強制する。LLM揺らぎをコードで吸収するため純関数で実装。
"""
from __future__ import annotations

import re

# cross判定に寄せる語（タイトル・概要のヒューリスティック）
_CROSS_WORDS = [
    "した話", "やってみた", "記録", "一年", "1年", "ヶ月", "か月", "月間",
    "入門", "ガイド", "まとめ", "比較", "設計", "実践", "戦略", "生存戦略",
    "武器庫", "教訓", "知見", "振り返り", "総括", "パターン", "とは",
]
# single判定に寄せる語（特定バグ・単一技術要素の修正記録）
# 強single語=固有エラー名等（cross語があっても優先）・弱single語=cross語で上書きされる
_SINGLE_STRONG_WORDS = [
    "ImportError", "UnicodeEncodeError", "UnicodeEncode", "surrogate",
    "サロゲート", "monkeypatch", "flaky", "タイポ", "exit code",
]
_SINGLE_WEAK_WORDS = [
    "エラー", "例外", "回避", "防ぐ", "修正法", "fix", "Fix", "競合", "衝突",
]
_SINGLE_RE = re.compile("|".join(re.escape(w) for w in _SINGLE_STRONG_WORDS))
_CROSS_RE = re.compile("|".join(re.escape(w) for w in _CROSS_WORDS))
_WEAK_SINGLE_RE = re.compile("|".join(re.escape(w) for w in _SINGLE_WEAK_WORDS))


def classify_topic_type(title: str, summary: str = "") -> str:
    """タイトル・概要から型（cross/single）を分類する純関数。

    優先順位: 強single語 > cross語 > 弱single語 > デフォルトsingle
    - 強single語（固有エラー名等）が含まれる → single（cross語があっても）
    - cross語（体験談・入門・設計等）のみ → cross
    - 弱single語のみ → single
    - どちらも無い → single側に倒す（cross量産の誤殺防止・安全側）
    """
    text = f"{title}\n{summary}"
    if _SINGLE_RE.search(text):
        return "single"
    if _CROSS_RE.search(text):
        return "cross"
    if _WEAK_SINGLE_RE.search(text):
        return "single"
    return "single"


def enforce_theme_ratio(topics: list, cross_ratio: float = 0.7) -> tuple:
    """提案トピック配列を型分類し、cross件数が不足なら再生成要求を返す。

    - 閾値は比率でなく件数比較（MLR r1修正・2026-09-23）: 「3件中2件以上cross」の
      プロンプト要求と `2/3=0.667 < 0.7` の比率比較が不整合になり、
      プロンプトどおりの提案まで恒常再生成されるバグを防ぐ
    - min_cross = max(1, round(len(topics) * cross_ratio)) → 3件なら2件
    - 非dict要素（LLMが壊れたJSONで文字列を混入）はself-inspect修正で耐性化:
      str()化して分類する（クラッシュで当日生成が止まらない・2026-09-23）
    - 単発型を削除はしない（捨てない設計・spec §4-1）
    - 戻り値: (topics, needs_regenerate)
    """
    if not topics:
        return topics, True

    def _title_summary(t):
        if isinstance(t, dict):
            return t.get("title", ""), t.get("summary", "")
        return str(t), ""

    n_cross = sum(
        1 for t in topics if classify_topic_type(*_title_summary(t)) == "cross")
    min_cross = max(1, round(len(topics) * cross_ratio))
    needs = n_cross < min_cross
    return topics, needs
