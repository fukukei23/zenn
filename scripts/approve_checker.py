#!/usr/bin/env python3
"""approve_checker.py — Discordリアクション判定→PAT転送approve（毎時cron・常駐なし）。

設計: docs/superpowers/specs/2026-11-26_zenn-discord-approval-design.md
- 判定対象: 未処理jsonエントリのみ
- 承認者ID照合（bot初期👍は構造的に除外）・絵文字正規化・hash照合
- 👍 → PATでissueに/approve転送（本文にDiscord由来記録）→ jsonエントリ削除
- 👎 → issue却下Close → jsonエントリ削除
- rejected状態+再👍 → issue再オープン+転送（誤却下自動復旧）
- ループ上限3回（再承認要求発行時のみインクリメント）・超過時手動確認降格
- hash不一致 → 再通知1日1回上限（旧メッセージに⚠️注記）
- 取得失敗≠未承認（fail-closed）・403/401はDiscordエラー通知
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord_api

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
ENTRIES_PATH = os.path.join(REPO_ROOT, "docs", "discord_messages.json")
REPO_FULL = "fukukei23/zenn"
LOOP_LIMIT = 3
KEEP_DAYS = 30
RENOTIFY_LIMIT_DAYS = 1


# ---------- 状態管理 ----------

def load_entries(path: str = ENTRIES_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_entries(path: str, entries: dict) -> None:
    """アトミック書込（tmp+rename）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def content_hash(article_path: str) -> str:
    """本文（frontmatter除外）のSHA-256を返す。"""
    with open(article_path, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cleanup_expired(entries: dict) -> dict:
    """30日超過エントリを清掃（created_at欠落は安全側で保持）。"""
    now = datetime.now(timezone.utc)
    kept = {}
    for k, v in entries.items():
        created = v.get("created_at")
        if not created:
            kept[k] = v
            continue
        try:
            dt = datetime.fromisoformat(created)
        except ValueError:
            kept[k] = v
            continue
        if now - dt < timedelta(days=KEEP_DAYS):
            kept[k] = v
    return kept


# ---------- GitHub操作 ----------

def gh_api(pat: str, method: str, path: str, json_body: dict | None = None) -> requests.Response:
    headers = {"Authorization": f"token {pat}", "Accept": "application/vnd.github.v3+json"}
    url = f"https://api.github.com/repos/{REPO_FULL}/{path}"
    return requests.request(method, url, headers=headers, json=json_body, timeout=30)


def post_approve_transfer(pat: str, issue_num: int, message_id: str, ts: str) -> None:
    """PATでissueに/approve転送（OWNER判定を通す・本文にDiscord由来記録）。"""
    body = (f"/approve\n\n<!-- via Discord reaction msg_id={message_id} at {ts} "
            f"(automated transfer by approve-check) -->")
    resp = gh_api(pat, "POST", f"issues/{issue_num}/comments", {"body": body})
    if resp.status_code in (401, 403):
        raise discord_api.DiscordAPIError(f"PAT認証エラー {resp.status_code}（PAT期限切れ・scope不足の疑い）")
    resp.raise_for_status()


def reopen_issue(pat: str, issue_num: int) -> None:
    resp = gh_api(pat, "PATCH", f"issues/{issue_num}", {"state": "open"})
    resp.raise_for_status()


def close_issue_reject(pat: str, issue_num: int) -> None:
    resp = gh_api(pat, "PATCH", f"issues/{issue_num}",
                  {"state": "closed", "state_reason": "not_planned"})
    resp.raise_for_status()


def notify_message_deleted(pat: str, issue_num: int) -> None:
    """Discordメッセージ404時にissueへ手動確認コメント（サイレント消失防止・MLR指摘採用）。"""
    body = ("⚠️ Discord承認メッセージが見つかりません（削除またはbot権限喪失の可能性）。\n"
            "このissueの承認待ち状態を解除しました。意図しない消失の場合は手動で/approveをコメントしてください。")
    resp = gh_api(pat, "POST", f"issues/{issue_num}/comments", {"body": body})
    resp.raise_for_status()


# ---------- 判定・処理 ----------

def get_decision(entry: dict) -> str:
    """エントリの承認判定をラップ（モック差し替え用の薄いラッパー）。"""
    return discord_api.get_approval_decision(
        entry["channel_id"], entry["message_id"],
        os.environ["DISCORD_BOT_TOKEN"], os.environ["DISCORD_APPROVER_USER_ID"])


def is_loop_exceeded(entry: dict) -> bool:
    return entry.get("attempts", 0) >= LOOP_LIMIT


def send_notify_message(entry: dict, slug: str, title: str, bot_token: str,
                        approver_user_id: str, webhook_url: str) -> str:
    """承認メッセージを送信し、entryを更新してmessage_idを返す（hash不一致再通知・再承認用）。"""
    content = (
        f"📝 Zenn記事ドラフトの承認をお願いします\n\n"
        f"**タイトル**: {title}\n**slug**: `{slug}`\n\n"
        f"**このメッセージの 👍 をタップすると公開処理が進みます**（自発で 👎 を付けると却下です）\n"
        f"通常は最長約90分以内で公開処理が進みます。誤って👎を付けた場合は、"
        f"このメッセージに再度👍を付けると復旧します。\n")
    try:
        mid = discord_api.send_message(entry["channel_id"], bot_token, content)
        discord_api.add_reaction(entry["channel_id"], mid, bot_token,
                                 discord_api.REACTION_APPROVE)
    except discord_api.DiscordAPIError as exc:
        discord_api.send_error_notification(webhook_url, f"notify送信失敗: {exc}")
        raise
    entry["message_id"] = mid
    today = datetime.now(timezone.utc).date().isoformat()
    entry["last_notify_date"] = today
    return mid


def handle_entry(entry: dict, issue_num: int, pat: str, webhook_url: str) -> str:
    """1エントリを処理する。返値: forwarded/reject/pending/recover/error。

    例外時にentryを変更した場合の整合は呼び出し側（main）がsave_entriesする。
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. 404=メッセージ削除 → 可視化コメント後エントリ削除（サイレント消失防止・MLR指摘採用）
    exists = discord_api.message_exists(entry["channel_id"], entry["message_id"],
                                        os.environ["DISCORD_BOT_TOKEN"])
    if not exists:
        try:
            notify_message_deleted(pat, issue_num)
        except Exception:
            pass  # コメント失敗でもエントリ処理は継続（best effort）
        return "deleted"

    # 2. 判定（取得失敗はfail-closed・何もせずerror通知）
    decision = get_decision(entry)
    if decision == "error":
        discord_api.send_error_notification(
            webhook_url, f"issue#{issue_num}: リアクション取得失敗（API・権限の疑い）")
        return "error"

    status = entry.get("status", "pending")

    # 3. rejected状態: 再👍で自動復旧（issue再オープン+即転送・specどおり・MLR指摘採用で転送追加）
    if status == "rejected":
        if decision == "approve":
            reopen_issue(pat, issue_num)
            post_approve_transfer(pat, issue_num, entry["message_id"], now_iso)
            entry["status"] = "pending"
            return "recover"
        return "pending"

    # 4. ループ上限超過 → 自動転送せず降格済み（上限到達通知は再送側で実施済み）
    if is_loop_exceeded(entry):
        return "loop_exceeded"

    # 5. hash照合（pending・reapproval共通）
    slug_path = os.path.join(REPO_ROOT, "articles",
                             f"{entry.get('slug', '')}.md")
    if entry.get("slug") and os.path.exists(slug_path):
        current_hash = content_hash(slug_path)
        if current_hash != entry["content_hash"]:
            today = datetime.now(timezone.utc).date().isoformat()
            if entry.get("renotified_date") == today:
                return "renotify_skipped"  # 再通知は1日1回上限（初回通知日と分離・MLR r2 GLM指摘採用）
            entry["content_hash"] = current_hash
            entry["status"] = "reapproval"
            entry["attempts"] = entry.get("attempts", 0) + 1
            if is_loop_exceeded(entry):
                discord_api.send_error_notification(
                    webhook_url, f"issue#{issue_num}: 再承認{LOOP_LIMIT}回超過 → 手動確認へ降格")
                return "loop_exceeded"
            # hash不一致再通知（notifier.build_approval_contentを流用・再送）
            from notifier import build_approval_content
            bot_token = os.environ["DISCORD_BOT_TOKEN"]
            content = build_approval_content(entry.get("slug", ""),
                                             entry.get("title", entry.get("slug", "")))
            mid = discord_api.send_message(entry["channel_id"], bot_token, content)
            discord_api.add_reaction(entry["channel_id"], mid, bot_token,
                                     discord_api.REACTION_APPROVE)
            entry["message_id"] = mid
            entry["renotified_date"] = today
            return "renotified"

    # 6. approve → PAT転送
    if decision == "approve":
        if status == "reapproval":
            entry["attempts"] = entry.get("attempts", 0) + 1
            if is_loop_exceeded(entry):
                discord_api.send_error_notification(
                    webhook_url, f"issue#{issue_num}: 再承認{LOOP_LIMIT}回超過 → 手動確認へ降格")
                return "loop_exceeded"
        post_approve_transfer(pat, issue_num, entry["message_id"], now_iso)
        return "forwarded"

    # 7. reject → issue却下Close（エントリはrejected保持・30日以内の再👍で復旧可能・MLR指摘採用）
    if decision == "reject":
        close_issue_reject(pat, issue_num)
        entry["status"] = "rejected"
        return "reject"

    return "pending"


BOT_USER_NAME = "github-actions[bot]"
BOT_USER_EMAIL = "github-actions[bot]@users.noreply.github.com"


def git_commit_push(message: str) -> None:
    """json変更をcommit+push（config→add/commit→pull --rebase→push順・fail-loud）。

    2026-11-28実測修復2件:
    ①pull --rebaseをadd/commit後に移動（73beb22と同型・forwarded時のentries.popで
    unstaged modifiedが生じpullが「cannot pull with rebase」で拒否・run 46108013219）。
    ②runnerにuser設定が無くcommitがexit 128で失敗してもcapture_outputでstderrが
    握り潰され静かなearly returnしていた（silent failure・mktemp隔離再現実験で
    COMMIT_EXIT=128実測）ためidentityを設定し・nothing to commit以外のcommit失敗は
    fail-loudに（順序回帰テスト: TestGitCommitPushOrder）。
    """
    subprocess.run(["git", "config", "user.name", BOT_USER_NAME],
                   cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", BOT_USER_EMAIL],
                   cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "add", os.path.relpath(ENTRIES_PATH, REPO_ROOT)],
                   cwd=REPO_ROOT, check=True)
    r = subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT,
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        if "nothing to commit" not in (r.stdout + r.stderr):
            raise RuntimeError(f"git commit失敗（identity・hook等の疑い）: {r.stderr[:200]}")
        return  # 変更なし等
    r = subprocess.run(["git", "pull", "--rebase"], cwd=REPO_ROOT,
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git pull --rebase失敗（競合の疑い・状態json未反映）: {r.stderr[:200]}")
    r = subprocess.run(["git", "push"], cwd=REPO_ROOT, capture_output=True, text=True,
                       check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git push失敗（状態json未反映・次回二重転送の可能性）: {r.stderr[:200]}")


def main() -> int:
    # 必須環境変数の早期検証（fail-fast・欠落時はKeyErrorでworkflow失敗）
    for var in ("DISCORD_BOT_TOKEN", "DISCORD_APPROVER_USER_ID", "GITHUB_PAT"):
        os.environ[var]
    pat = os.environ["GITHUB_PAT"]
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")

    entries = load_entries()
    if not entries:
        return 0

    actions = {}
    for key in list(entries.keys()):
        issue_num = int(key)
        entry = entries[key]
        slug = entry.get("slug", "")
        article_path = os.path.join(REPO_ROOT, "articles", f"{slug}.md")
        if entry.get("slug") and not os.path.exists(article_path):
            continue  # slug未記録エントリ（旧データ）はhash照合のみスキップ
        try:
            result = handle_entry(entry, issue_num, pat, webhook_url)
        except (discord_api.DiscordAPIError, requests.RequestException) as exc:
            # PAT期限切れ等の401/403も通知へ出す（MLR指摘採用・静かなworkflow失敗防止）
            discord_api.send_error_notification(webhook_url, f"issue#{issue_num}: {exc}")
            result = "error"
        actions[key] = result
        if result in ("forwarded", "recover", "deleted"):
            entries.pop(key)  # 転送成功・復旧・削除でエントリ除去（rejectはrejected保持・MLR指摘採用）

    entries = cleanup_expired(entries)

    if actions:
        save_entries(ENTRIES_PATH, entries)
        try:
            git_commit_push("chore: approve-check状態更新（自動）")
        except RuntimeError as exc:
            discord_api.send_error_notification(
                webhook_url, f"状態jsonのpush失敗: {exc}")
            print(json.dumps(actions, ensure_ascii=False))
            return 1
        print(json.dumps(actions, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
