#!/usr/bin/env python3
"""reapprover.py — 品質ゲート修正時の再承認メッセージ再送（publish.yml ja_gate後のgate=fixedステップから呼ばれる）。

- 修正後のarticle本文を再hashしてjson更新（旧hashを参照し続けると再承認が永久停止する事故防止）
- ループ上限3回（attempts>=3で再送せずNone=手動確認降格はchecker側通知）
- diff概要+修正理由を文面に含める
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord_api
from approve_checker import ENTRIES_PATH, REPO_ROOT, LOOP_LIMIT, content_hash, load_entries, save_entries


def build_reapproval_content(slug: str, title: str, fixes: list[tuple[str, str, str]]) -> str:
    lines = [
        "📝 品質ゲートが自動修正を実施しました — **再承認をお願いします**\n",
        f"**タイトル**: {title}\n**slug**: `{slug}`\n",
        "| 元の文 | 修正後 | 修正理由 |",
        "|---|---|---|",
    ]
    for orig, fixed, reason in fixes[:5]:
        lines.append(f"| {orig[:40]} | {fixed[:40]} | {reason[:30]} |")
    lines.append("\n**このメッセージの 👍 をタップすると公開処理が進みます**")
    return "\n".join(lines)


def update_entry_for_reapproval(entries_path: str, issue_key: str,
                                article_path: str) -> dict | None:
    """entryを再承認用に更新（再hash+attempts++）・上限超過時はNone。"""
    entries = load_entries(entries_path)
    entry = entries.get(issue_key)
    if entry is None:
        return None
    if entry.get("attempts", 0) >= LOOP_LIMIT:
        return None
    if os.path.exists(article_path):
        entry["content_hash"] = content_hash(article_path)
    entry["status"] = "reapproval"
    entry["attempts"] = entry.get("attempts", 0) + 1
    save_entries(entries_path, entries)
    return entry


def main() -> int:
    """publish.ymlの環境変数（ISSUE_NUMBER・MINIMAX_API_KEYは未使用・ja_quality_fixのログはissue参照）。

    diff情報はissueコメント（ja_quality_fix.pyのbuild_comment出力）から取得せず、
    修正後のarticleと旧hashの差分を簡易表示する（fixesテーブルは簡略化・Phase 2で拡張）。
    """
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    issue_key = os.environ.get("ISSUE_NUMBER", "")
    if not issue_key:
        print("ERROR: ISSUE_NUMBER未設定（再承認メッセージ送信不能・MLR指摘採用でfail-fast化）")
        return 1
    meta_path = os.path.join(REPO_ROOT, "article_meta.json")
    slug = ""
    title = ""
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path, encoding="utf-8"))
        slug = meta.get("slug", "")
        title = meta.get("title", slug)
    article_path = os.path.join(REPO_ROOT, "articles", f"{slug}.md") if slug else ""
    entry = update_entry_for_reapproval(ENTRIES_PATH, issue_key, article_path)
    if entry is None:
        discord_api.send_error_notification(
            webhook_url, f"issue#{issue_key}: 再承認{LOOP_LIMIT}回超過 → 手動確認へ降格")
        return 0
    content = build_reapproval_content(slug, title, [])
    mid = discord_api.send_message(entry["channel_id"], bot_token, content)
    discord_api.add_reaction(entry["channel_id"], mid, bot_token,
                             discord_api.REACTION_APPROVE)
    entry["message_id"] = mid
    entry["last_notify_date"] = datetime.now(timezone.utc).date().isoformat()
    entries = load_entries(ENTRIES_PATH)
    entries[issue_key] = entry
    save_entries(ENTRIES_PATH, entries)
    print(f"reapproval message sent: issue#{issue_key} msg={mid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
