#!/usr/bin/env python3
"""Send Discord notification and create GitHub Issue for draft review."""

import json
import os
import sys

import requests

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_FULL = "fukukei23/zenn"


def load_meta():
    path = os.path.join(SCRIPTS_DIR, "..", "article_meta.json")
    if not os.path.exists(path):
        print("No article_meta.json found")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def send_discord(webhook_url, meta):
    slug = meta["slug"]
    title = meta["title"]
    repo = meta.get("repo", "")
    preview_url = f"https://github.com/{REPO_FULL}/blob/main/articles/{slug}.md"

    message = {
        "content": f"""**新着記事ドラフトが出来ました**

**タイトル**: {title}
**リポジトリ**: {repo}
**プレビュー**: {preview_url}

:white_check_mark: 公開OK → Issueに `/approve` とコメント
:pencil2: 修正 → 記事ファイルを編集後に `/approve`
:x: 却下 → IssueをClose""",
    }

    resp = requests.post(webhook_url, json=message, timeout=15)
    if resp.ok:
        print(f"Discord notification sent")
    else:
        print(f"Discord failed: {resp.status_code} {resp.text[:200]}")


def create_issue(token, meta):
    slug = meta["slug"]
    title = meta["title"]
    summary = meta.get("summary", "")
    repo = meta.get("repo", "")
    preview_url = f"https://github.com/{REPO_FULL}/blob/main/articles/{slug}.md"

    issue_body = f"""## 記事ドラフト: {title}

- **slug**: `{slug}`
- **元リポジトリ**: {repo}
- **概要**: {summary}
- **プレビュー**: {preview_url}

---

### 承認方法

- `/approve` とコメント → 公開+SNS投稿が自動実行されます
- IssueをClose → ドラフトは `published: false` のまま残ります

<!-- slug: {slug} -->
"""

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "title": f"[Draft] {slug}",
        "body": issue_body,
        "labels": ["draft-review"],
    }

    resp = requests.post(
        f"https://api.github.com/repos/{REPO_FULL}/issues",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.ok:
        issue = resp.json()
        print(f"Issue created: #{issue['number']} — {issue['html_url']}")
        return issue["number"]
    else:
        print(f"Issue creation failed: {resp.status_code} {resp.text[:200]}")
        return None


def main():
    meta = load_meta()
    if not meta:
        sys.exit(1)

    # Discord notification
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if webhook_url:
        send_discord(webhook_url, meta)
    else:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord notification")

    # GitHub Issue
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        issue_number = create_issue(token, meta)
        if issue_number:
            meta["issue_number"] = issue_number
            meta_path = os.path.join(SCRIPTS_DIR, "..", "article_meta.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
    else:
        print("GITHUB_TOKEN not set, skipping Issue creation")


if __name__ == "__main__":
    main()
