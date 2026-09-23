#!/usr/bin/env python3
"""run_bundle.py — 群化提案の生成ランナー（self-inspect修正でリポジトリ保存・2026-09-23）

下書き記事のうち「C級&単発型」を抽出し、テーマ語で束ねてまとめ記事の目次案を
docs/群化提案.md に書き出す。決定的（LLM呼出なし）・何度実行しても同じ結果。

使い方: python3 scripts/run_bundle.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundler import bundle_proposals, group_by_theme  # noqa: E402
from ranker import parse_frontmatter, parse_ranking_md  # noqa: E402
from theme_policy import classify_topic_type  # noqa: E402

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RANKING = os.path.join(REPO, "docs", "公開ランキング.md")
OUT = os.path.join(REPO, "docs", "群化提案.md")
C_GRADE_THRESHOLD = 14  # C級=スコア13以下（ranker.py GRADE_RANGESと整合）


def main() -> int:
    ranked = {r["file"]: r for r in parse_ranking_md(RANKING)}
    drafts = []
    total_drafts = 0
    for p in sorted(glob.glob(os.path.join(REPO, "articles", "*.md"))):
        fm = parse_frontmatter(p)
        if fm["published"]:
            continue
        total_drafts += 1
        r = ranked.get(os.path.basename(p))
        score = r["score"] if r else None
        is_c = (score is None) or (score < C_GRADE_THRESHOLD)
        if not is_c:
            continue
        if classify_topic_type(fm["title"], "") != "single":
            continue  # spec: C級「単発」を群化対象に
        drafts.append({"file": os.path.basename(p), "title": fm["title"],
                       "tags": fm["topics"]})

    print(f"下書き総数: {total_drafts} / 群化候補(C級&単発型): {len(drafts)}")
    groups = group_by_theme(drafts)
    proposals = bundle_proposals(groups, min_size=3)
    print(f"テーマ群: {len(groups)} / 提案: {len(proposals)}件")

    lines = ["# 群化提案（まとめ記事目次案・自動生成）", "",
             "> run_bundle.pyによる決定的生成・本文化は人間承認後", ""]
    for pr in proposals:
        lines.append(f"## {pr['title']}")
        lines.append("")
        for ch in pr["chapters"]:
            lines.append(f"- {ch['chapter']}（`{ch['files'][0]}`）")
        lines.append("")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"書込: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
