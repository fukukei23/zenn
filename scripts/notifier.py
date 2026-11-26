#!/usr/bin/env python3
"""Send Discord notification and create GitHub Issue for draft review."""

import json
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord_api as _api

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
        print("Discord notification sent")
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


def load_validation_errors(base_dir=None):
    """generator が違反記事をskipした記録（validation_errors.json）。"""
    target_dir = base_dir or os.path.join(SCRIPTS_DIR, "..")
    path = os.path.join(target_dir, "validation_errors.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_generator_error(base_dir=None):
    """generator が予期せぬ例外で crash した記録（generator_error.json）。
    API例外（429/500/timeout 等）の静かな crash を notifier が検知して通知
    するための経路。"""
    target_dir = base_dir or os.path.join(SCRIPTS_DIR, "..")
    path = os.path.join(target_dir, "generator_error.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def notify_generator_error(err, webhook_url):
    """generator 例外通知（Discord + GitHub Step Summary）。API例外等で
    記事生成できなかった旨を通知し、沈黙の crash を可視化する。"""
    err_type = err.get("type", "Unknown")
    message = err.get("message", "")
    tb = err.get("traceback", "")
    lines = [
        f"🚨 **generator が例外で停止** ({err_type}) "
        "- 記事生成できず・要確認",
        f"• message: {message}",
    ]
    if tb:
        lines.append("• traceback（先頭5行）:")
        for line in tb.splitlines()[:5]:
            lines.append(f"  {line}")

    if webhook_url:
        resp = requests.post(
            webhook_url, json={"content": "\n".join(lines)}, timeout=15
        )
        status = "sent" if resp.ok else f"failed({resp.status_code})"
        print(f"Discord (generator-error): {status}")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n\n## 🚨 generator 例外停止\n\n")
            f.write(f"- **type**: {err_type}\n")
            f.write(f"- **message**: {message}\n")
            f.write(f"```\n{tb}\n```\n")


def notify_validation(verrs, webhook_url):
    """違反skip通知（閾値撤廃・毎回通知）。Discord + GitHub Step Summary に併用出力。"""
    errs = verrs.get("errors", [])
    lines = [
        f"⚠️ **Zenn記事バリデーション違反（{len(errs)}件）** "
        "- デプロイ中断防止のためskipしました"
    ]
    for e in errs:
        lines.append(f"• `{e['slug']}`")
        lines.append(f"  タイトル: {e['title']}")
        lines.append(f"  違反: {' / '.join(e['errors'])}")
        lines.append(f"  退避先: {e.get('skipped_path', '.skipped/')}")

    if webhook_url:
        resp = requests.post(
            webhook_url, json={"content": "\n".join(lines)}, timeout=15
        )
        status = "sent" if resp.ok else f"failed({resp.status_code})"
        print(f"Discord (validation): {status}")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n\n## ⚠️ Zenn記事バリデーション違反\n\n")
            for e in errs:
                f.write(
                    f"- `{e['slug']}` ({e['title']}): "
                    f"{' / '.join(e['errors'])}\n"
                )


def main():
    # 優先0: generator 例外（API例外等でcrash・沈黙防止）
    gerr = load_generator_error()
    if gerr:
        notify_generator_error(gerr, os.environ.get("DISCORD_WEBHOOK_URL", ""))
        return  # 例外時は他の通知スキップ

    # 優先1: バリデーション違反通知（generator が違反記事をskipした時）
    verrs = load_validation_errors()
    if verrs:
        notify_validation(verrs, os.environ.get("DISCORD_WEBHOOK_URL", ""))
        return  # sys.exit(1)→return: 違反通知は送信済み・Step Summaryで可視化

    # 通常：新着draft通知
    meta = load_meta()
    if not meta:
        # 記事生成なし（skip.flag 等）は正常終了
        return

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


def resolve_channel_id(webhook_url: str) -> str:
    """webhook URLからchannel_idを解決（失敗時はwebhook送信にフォールバックするため呼び出し側で処理）。"""
    return _api.resolve_channel_id_from_webhook(webhook_url)


def build_approval_content(slug: str, title: str) -> str:
    """承認メッセージ文面（誘導・所要時間・誤却下復旧手順を含む）。"""
    return (
        f"📝 Zenn記事ドラフトの承認をお願いします\n\n"
        f"**タイトル**: {title}\n**slug**: `{slug}`\n\n"
        f"**このメッセージの 👍 をタップすると公開処理が進みます**（自発で 👎 を付けると却下です）\n"
        f"通常は最長約90分以内で公開処理が進みます。\n"
        f"誤って 👎 を付けた場合は、このメッセージに再度 👍 を付けると復旧します。\n")


def build_entry(slug: str, article_path: str, channel_id: str, message_id: str,
                title: str = "") -> dict:
    """jsonエントリを構築する（hash照合・ループ管理・rejected保持の元データ）。"""
    from approve_checker import content_hash
    return {
        "message_id": message_id,
        "channel_id": channel_id,
        "slug": slug,
        "title": title,
        "content_hash": content_hash(article_path),
        "status": "pending",
        "attempts": 0,
        "last_notify_date": datetime.now(timezone.utc).date().isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def send_approval_message(meta: dict, entries_path: str, bot_token: str,
                          webhook_url: str, article_path: str,
                          issue_num: int) -> dict:
    """承認メッセージをbot送信+初期👍付与+json記録。entryを返す。

    webhookからchannel_idを解決 → bot送信 → 👍初期付与 → entries.jsonに記録。
    """
    slug = meta["slug"]
    title = meta.get("title", slug)
    channel_id = resolve_channel_id(webhook_url)
    content = build_approval_content(slug, title)
    message_id = _api.send_message(channel_id, bot_token, content)
    _api.add_reaction(channel_id, message_id, bot_token, _api.REACTION_APPROVE)

    entries = json.load(open(entries_path, encoding="utf-8")) if os.path.exists(entries_path) else {}
    entries[str(issue_num)] = build_entry(slug, article_path, channel_id, message_id, title)
    tmp = entries_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, entries_path)
    return entries[str(issue_num)]


if __name__ == "__main__":
    main()
