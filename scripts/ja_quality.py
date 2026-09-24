#!/usr/bin/env python3
"""ja_quality.py — Zenn記事の日本語品質gate（2026-09-23・ふくけい承認A案）

きっかけ: まとめ記事の「自分は大丈夫と思って読んでいただけると思っています」
（主語すり替え+「思って」二重の破綻文）が validate_all_articles.py の技術的検証を
すり抜けて公開候補になった事故の再発防止。

LLM（MiniMax）に本文の破綻文を点検させ、指摘があれば exit 1 で止める。
技術的検証（validate_all_articles.py の既存チェック）とは層が違い、
デフォルト実行には掛からない（--ja-quality フラグ時のみ＝公開前の手動gate）。

使い方:
    python3 scripts/ja_quality.py articles/xxx.md [yyy.md ...]
    python3 scripts/validate_all_articles.py --ja-quality articles/xxx.md
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generator import chat, MINIMAX_BASE_URL, TOPIC_MODEL  # noqa: E402

# 推論モデル（MiniMax-M3）は点検タスクでreasoningに大量トークンを消費する実測
# （2026-09-24 Phase 0項目②実測: 16000では4k字入力でも16%がlength切れ・P95がキャップ打ち切り）
# → 24000へ引上げ（M3のmax output上限は262144を確認済み・OpenRouter仕様）
# 環境変数 JA_QUALITY_MAX_TOKENS でオーバーライド可能（Phase 0項目④・v4推奨）
CHECK_MAX_TOKENS = int(os.environ.get("JA_QUALITY_MAX_TOKENS", "24000"))


def split_frontmatter(text: str) -> tuple:
    """frontmatter(title)と本文を分離する。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return "", text
    fm = m.group(1)
    tm = re.search(r'^title:\s*"?(.*?)"?\s*$', fm, re.MULTILINE)
    title = tm.group(1) if tm else ""
    return title, text[m.end():]


def build_prompt(title: str, body: str) -> str:
    """日本語品質点検のプロンプトを組み立てる（純関数）。"""
    return f"""以下のZenn技術記事を日本語の品質観点で点検してください。

タイトル: {title}

本文:
{body}

点検する観点（壊れた日本語・読者を混乱させる文）:
- 意味が成立しない文（文全体として主語と述語の対応が崩れ、何についての何かが読み取れない最上位の破綻）
- 主語のすり替え・不明（誰が・何が、途中で変わる文）
- 同じ言葉の二重使用による意味不明（例: 「思って…と思っています」）
- 誤字脱字・変な助詞
- 意味が通らない長文・翻訳調の破綻
- 「読んでいただけると思っています」型の文法的におかしい敬語

※ コードブロック・インラインコード（`...` 内・```ブロック内）の文字列・ログ・エラーメッセージ
  はプログラムコードなので日本語点検の対象外です。本文の説明文のみを対象にしてください。
※ 文体の好み（口語/丁寧語の揺れ程度）は指摘しないでください。読者が混乱する破綻のみ。

出力形式（JSONのみ・説明文・前置き・コードフェンスなし・厳密な有効JSON）:
{{"issues": [{{"quote": "問題の文の抜粋", "problem": "何が問題か", "suggestion": "修正案"}}]}}

問題が1つもなければ {{"issues": []}} のみを返してください。"""


def extract_json_block(text: str) -> str | None:
    """応答テキストから最初の {...} ブロックを抽出する（壊れ耐性・見つからなければNone）。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group() if m else None


def parse_issues(text: str) -> list | None:
    """LLM応答からissues配列を抽出する。JSON無しはNone（点検不能）。"""
    block = extract_json_block(text)
    if block is None:
        return None
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "issues" not in data:
        return None
    return data["issues"]


APPLY_LIMIT_CHARS = 12000  # 実用上限（2026-09-24実測: ≤12k字は全長成功・16k字で3連続length切れ）


def length_warning(body: str) -> str | None:
    """本文が実用上限（12k字）を超える場合の警告文を返す（超えていなければNone）。"""
    if len(body) <= APPLY_LIMIT_CHARS:
        return None
    return (f"本文が{len(body)}字で実用上限の12000字を超えています。"
            f"分割点検を推奨（16k字超は点検不能になる実測あり）")


def check_file(client, path: str, max_retries: int = 3) -> list | None:
    """1ファイルをLLM点検する。issuesリスト（0件=合格）/None=点検不能。"""
    with open(path, encoding="utf-8") as f:
        title, body = split_frontmatter(f.read())
    warn = length_warning(body)
    if warn:
        print(f"  [warn] {os.path.basename(path)}: {warn}", file=sys.stderr)
    prompt = build_prompt(title, body)
    for _attempt in range(max_retries):
        text = chat(client, TOPIC_MODEL, prompt, max_tokens=CHECK_MAX_TOKENS)
        issues = parse_issues(text)
        if issues is not None:
            return issues
        # 壊れた応答は再試行（generator.extract_topicsと同じ堅牢パターン）
    print(f"  [warn] {os.path.basename(path)}: LLM応答を{max_retries}回パースできず点検不能", file=sys.stderr)
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    from openai import OpenAI

    try:
        client = OpenAI(
            api_key=os.environ["MINIMAX_API_KEY"],
            base_url=MINIMAX_BASE_URL,
        )
    except KeyError:
        print("❌ MINIMAX_API_KEY が未設定です", file=sys.stderr)
        return 2
    rc = 0
    for path in sys.argv[1:]:
        issues = check_file(client, path)
        if issues is None:
            continue  # 点検不能は警告のみ（fail-safe・blockはしない）
        for it in issues:
            print(f"❌ {os.path.basename(path)}: {it.get('problem', '?')}")
            print(f"   該当: {it.get('quote', '?')[:60]}")
            print(f"   修正案: {it.get('suggestion', '?')[:60]}")
            rc = 1
        if not issues:
            print(f"✅ {os.path.basename(path)}: 日本語品質OK")
    return rc


if __name__ == "__main__":
    sys.exit(main())
