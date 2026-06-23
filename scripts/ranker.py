#!/usr/bin/env python3
"""Update docs/公開ランキング.md — score new articles (MiniMax) and rebuild ranking.

未登録記事をMiniMaxで3軸採点（バズり度/技術深度/重要度）して追加し、
全体をスコア降順（同スコアは既存順位維持）で再ソート・級(S/A/B/C)再分類して
ランキングmd全体を再生成する。既存記事のスコア・いいね数は維持（冪等）。
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

import yaml
from openai import OpenAI

# generator.py から chat・定数を再利用（DRY・generator.py は __main__ ガード付きで import 安全）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generator import chat, MINIMAX_BASE_URL, TOPIC_MODEL  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(SCRIPTS_DIR, "..")
RANKING_PATH = os.path.join(REPO_DIR, "docs", "公開ランキング.md")
ARTICLES_DIR = os.path.join(REPO_DIR, "articles")

# 級分類: (級名, (下限, 上限), 説明)
GRADE_RANGES = [
    ("S", (20, 999), "スコア20+、面接・転職に直結"),
    ("A", (17, 19), "スコア17-19、技術アピールに有効"),
    ("B", (14, 16), "スコア14-16、着実な技術発信"),
    ("C", (0, 13), "スコア13以下、入門・ニッチ"),
]

HEADER_TMPL = """# Zenn記事公開ランキング（{today}）

> バズり度・技術深度・重要度を1-10で評価
> 最終更新: {today}

## 評価基準

| 指標 | 説明 |
|---|---|
| バズり度 | Zenn/はてなブックマーク等での反応期待値 |
| 技術深度 | 内容が専門的か・独自ノウハウか |
| 重要度 | キャリア・就活でのアピール度 |
| 合計 | 高いほど優先して公開 |

---

## ランキング（{count}件）

"""

GRADE_TMPL = "### {grade}級（{desc}）\n\n"
TABLE_HEADER = (
    "| 順位 | スコア | ファイル | 日本語タイトル | バズ | 技術 | 重要 | 状態 | ❤ |\n"
    "|------|--------|----------|---------------|------|------|------|------|---|\n"
)


def parse_ranking_md(path):
    """ランキングmdのテーブル行を抽出し、dictのリストを返す。existing_index付き。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    records = []
    # | 順位 | スコア | `file.md` | タイトル | バズ | 技術 | 重要 | 状態 | ❤ |
    pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*(\d+)\s*\|\s*`([^`]+\.md)`\s*\|\s*(.*?)\s*\|"
        r"\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*([^\s|]+)\s*\|\s*$",
        re.M,
    )
    for idx, m in enumerate(pattern.finditer(text)):
        records.append({
            "file": m.group(2),
            "title": m.group(3).strip().replace("\\|", "|"),
            "score": int(m.group(1)),
            "buzz": int(m.group(4)),
            "tech": int(m.group(5)),
            "importance": int(m.group(6)),
            "status": m.group(7),
            "likes": m.group(8),
            "existing_index": idx,
        })
    return records


def parse_frontmatter(path):
    """記事mdの frontmatter（title/topics/published）と本文先頭を返す。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {"title": os.path.basename(path), "topics": [], "published": False, "body_preview": ""}
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        data = {}
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    return {
        "title": data.get("title", os.path.basename(path)),
        "topics": data.get("topics", []) or [],
        "published": bool(data.get("published", False)),
        "body_preview": body[:800],
    }


def discover_unranked(ranked, articles_dir):
    """articles/ のうちランキング未登録のファイル名を返す（ソート済み）。"""
    ranked_files = {r["file"] for r in ranked}
    return [
        os.path.basename(p)
        for p in sorted(glob.glob(os.path.join(articles_dir, "*.md")))
        if os.path.basename(p) not in ranked_files
    ]


def clamp_score(v):
    """1-10整数に正規化。"""
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(1, min(10, v))


def score_article(client, title, summary, tags):
    """MiniMaxで3軸採点。最大3回リトライ。失敗時None。

    generator.extract_topics の堅牢パターン（リトライ付きJSONパース）を踏襲。
    """
    prompt = f"""以下のZenn技術記事を3つの指標で1-10点（整数）で採点してください。

タイトル: {title}
タグ: {', '.join(tags) if tags else ''}
記事本文先頭:
{summary}

指標:
- buzz（バズり度）: Zenn/はてなブックマーク等での反応期待値（1-10）
- tech（技術深度）: 内容が専門的か・独自ノウハウか（1-10）
- importance（重要度）: 非IT公務員からIT転職するキャリア・就活でのアピール度（1-10）

出力形式（JSONのみ・説明文・前置き・コードフェンスなし・厳密な有効JSON）:
{{"buzz": 7, "tech": 8, "importance": 6}}"""

    # MiniMaxはJSON出力が揺らぐため5回リトライ（generator.extract_topics と同じ堅牢パターン）
    for _attempt in range(5):
        text = chat(client, TOPIC_MODEL, prompt, max_tokens=300)
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            continue
        try:
            data = json.loads(m.group())
            buzz = clamp_score(data["buzz"])
            tech = clamp_score(data["tech"])
            importance = clamp_score(data["importance"])
            if None in (buzz, tech, importance):
                continue
            return {"buzz": buzz, "tech": tech, "importance": importance}
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return None


def grade(score):
    """スコア→級。"""
    for g, (lo, hi), _desc in GRADE_RANGES:
        if lo <= score <= hi:
            return g
    return "C"


def rank_sort(records):
    """スコア降順・同スコアは既存順位維持の安定ソート。"""
    return sorted(records, key=lambda r: (-r["score"], r["existing_index"]))


def render_md(records, today):
    """ランキングmd全体を再生成。"""
    out = [HEADER_TMPL.format(today=today, count=len(records))]
    for g, (_lo, _hi), desc in GRADE_RANGES:
        in_grade = [r for r in records if grade(r["score"]) == g]
        if not in_grade:
            continue
        out.append(GRADE_TMPL.format(grade=g, desc=desc))
        out.append(TABLE_HEADER)
        for i, r in enumerate(in_grade, 1):
            title_esc = r["title"].replace("|", "\\|")
            out.append(
                f"| {i} | {r['score']} | `{r['file']}` | {title_esc} "
                f"| {r['buzz']} | {r['tech']} | {r['importance']} "
                f"| {r['status']} | {r['likes']} |\n"
            )
        out.append("\n")
    return "".join(out)


def validate(new_md, expected_count):
    """再生成mdの健全性チェック（テーブル行数＝期待件数）。"""
    rows = re.findall(r"^\|\s*\d+\s*\|\s*\d+\s*\|", new_md, re.M)
    return len(rows) == expected_count


def sync_status(records, articles_dir):
    """全記事のstatusをfrontmatter published で補正（要件4・全件同期）。"""
    for r in records:
        path = os.path.join(articles_dir, r["file"])
        if os.path.exists(path):
            try:
                fm = parse_frontmatter(path)
                r["status"] = "published" if fm.get("published") else "draft"
            except Exception:
                pass  # 読めなければ既存値維持


def main():
    parser = argparse.ArgumentParser(description="Update docs/公開ランキング.md")
    parser.add_argument("--dry-run", action="store_true", help="stdoutに出力・書き込まない")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    records = parse_ranking_md(RANKING_PATH)
    old_count = len(records)

    unranked = discover_unranked(records, ARTICLES_DIR)
    if not unranked:
        print("No new articles to rank")
        return

    print(f"Unranked articles: {len(unranked)}")
    client = OpenAI(api_key=os.environ["MINIMAX_API_KEY"], base_url=MINIMAX_BASE_URL)

    next_index = len(records)
    added = 0
    for fname in unranked:
        path = os.path.join(ARTICLES_DIR, fname)
        try:
            fm = parse_frontmatter(path)
            score = score_article(client, fm["title"], fm["body_preview"], fm["topics"])
            if score is None:
                print(f"  SKIP (score failed): {fname}")
                continue
            total = score["buzz"] + score["tech"] + score["importance"]
            records.append({
                "file": fname,
                "title": fm["title"],
                "score": total,
                "buzz": score["buzz"],
                "tech": score["tech"],
                "importance": score["importance"],
                "status": "published" if fm.get("published") else "draft",
                "likes": "-",
                "existing_index": next_index + added,
            })
            added += 1
            print(f"  + {fname}: buzz={score['buzz']} tech={score['tech']} "
                  f"imp={score['importance']} (= {total}, {grade(total)}級)")
        except Exception as e:  # 個別スキップ（部分失敗で全体は壊さない）
            print(f"  SKIP (error: {e}): {fname}")
            continue

    if added == 0:
        print("No articles scored. Keeping ranking unchanged.")
        return

    # 既存記事含む全件のstatusをfrontmatterで同期
    sync_status(records, ARTICLES_DIR)

    records = rank_sort(records)
    new_md = render_md(records, today)

    if not validate(new_md, len(records)):
        print("VALIDATION FAILED. Keeping ranking unchanged.")
        return

    if args.dry_run:
        print("\n--- DRY RUN (not written) ---\n")
        print(new_md)
        return

    with open(RANKING_PATH, "w", encoding="utf-8") as f:
        f.write(new_md)
    print(f"Updated: docs/公開ランキング.md ({old_count} -> {len(records)} articles)")


if __name__ == "__main__":
    main()
