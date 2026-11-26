#!/usr/bin/env python3
"""notifier_send_approval.py — discover.yml用ラッパー: issue番号を取得し承認メッセージを送信。

issue番号は notifier.main が article_meta.json に issue_number として記録する
（notifier.py L213・2026-11-26実装時点で実在）ためそれを優先し、
旧データ等で欠落している場合のみissue一覧APIからslug一致を検索する
（冪等・重複送信はjson上書きで自然回避）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import notifier

REPO_FULL = "fukukei23/zenn"
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)


def find_issue_number(token: str, slug: str) -> int | None:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(
        f"https://api.github.com/repos/{REPO_FULL}/issues",
        params={"labels": "draft-review", "state": "open", "per_page": "10",
                "sort": "created", "direction": "desc"},
        headers=headers, timeout=30)
    resp.raise_for_status()
    for issue in resp.json():
        if f"<!-- slug: {slug} -->" in issue.get("body", ""):
            return issue["number"]
    return None


def main() -> int:
    meta = notifier.load_meta()
    if not meta:
        return 0
    token = os.environ["GITHUB_TOKEN"]
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not bot_token or not webhook_url:
        print("DISCORD_BOT_TOKEN/DISCORD_WEBHOOK_URL未設定 → 承認メッセージ送信をスキップ")
        return 0
    issue_num = meta.get("issue_number") or find_issue_number(token, meta["slug"])
    if issue_num is None:
        print("対応するissueが見つからずスキップ")
        return 0
    entries_path = os.path.join(REPO_ROOT, "docs", "discord_messages.json")
    article_path = os.path.join(REPO_ROOT, "articles", f"{meta['slug']}.md")
    entry = notifier.send_approval_message(meta, entries_path, bot_token,
                                           webhook_url, article_path, issue_num)
    print(f"approval message sent: issue#{issue_num} msg={entry['message_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
