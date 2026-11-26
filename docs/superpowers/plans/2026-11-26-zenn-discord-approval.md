# Zenn Discord承認パイプライン Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** スマホのDiscord通知→👍リアクション1タップで承認→最大約90分以内に自動公開される人間参加型パイプラインを実装する。

**Architecture:** 既存discover.yml（ドラフト発見）とpublish.yml（公開・ja_gate付き）は変更せず、間に「Discord bot通知→リアクション判定→PAT転送approve」の層を挿入する。状態は`docs/discord_messages.json`で管理し、GitHub Actionsの毎時cronがリアクションを判定して転送する。

**Tech Stack:** Python 3.12・requests（Discord REST API・GitHub API）・pytest・GitHub Actions

**spec:** `docs/superpowers/specs/2026-11-26_zenn-discord-approval-design.md`（commit 2d1eb30）

**実装上の既知事実:**
- PAT投稿コメント=OWNER・github-actions[bot]=CONTRIBUTOR（API実測済み）→ PAT転送でpublish.yml:16のOWNER判定を通る
- publish.yml:45のif条件は`gate=='clean'`のみ → gate=fixed時は公開ステップ自動スキップ（再送ステップはそこに追加）
- X自動化lib/discord_client.pyの`get_approval_decision`は承認者ID照合方式（本計画のTask 1は同型をzenn側に独立配置するもの）
- workflows/publish.ymlの secrets: DISCORD_WEBHOOK_URL・GITHUB_TOKEN・MINIMAX_API_KEY・PERSONAL_ACCESS_TOKEN はGitHub secrets登録済み・**DISCORD_BOT_TOKENは未登録（Task 7で登録）**
- 自セッションのpaths.json宣言（553c）には本計画の全対象ファイルが登録済み（git commit-scodedで検証される）

---

### Task 1: discord_api.py — Discord REST API薄ラッパー

**Files:**
- Create: `scripts/discord_api.py`
- Test: `tests/test_discord_api.py`

- [ ] **Step 1: 失敗テストを書く**

```python
"""tests/test_discord_api.py — discord_api.pyの単体テスト（モック使用・API呼び出しなし）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import discord_api
import pytest


class TestNormalizeEmoji:
    def test_thumb_up_codepoint(self):
        assert discord_api.normalize_emoji("\U0001F44D") == "approve"

    def test_thumb_down_codepoint(self):
        assert discord_api.normalize_emoji("\U0001F44E") == "reject"

    def test_discord_name_thumbsup(self):
        assert discord_api.normalize_emoji("thumbsup") == "approve"

    def test_discord_shortname(self):
        assert discord_api.normalize_emoji(":+1:") == "approve"
        assert discord_api.normalize_emoji(":-1:") == "reject"

    def test_unknown_emoji_passthrough(self):
        assert discord_api.normalize_emoji("eyes") == "eyes"


class TestGetApprovalDecision:
    """承認者ID照合（X自動化get_approval_decisionと同型）。"""

    def test_approver_thumb_up_is_approve(self, monkeypatch):
        monkeypatch.setattr(
            discord_api, "_get_reaction_user_ids",
            lambda cid, mid, tok, emoji: {"123"} if emoji == "approve" else set())
        assert discord_api.get_approval_decision("c1", "m1", "tok", "123") == "approve"

    def test_approver_thumb_down_wins_over_up(self, monkeypatch):
        """👍と👎が両方付いた場合: 👎優先（安全側）。"""
        def fake_users(cid, mid, tok, emoji):
            return {"123"}  # 承認者が両方にリアクションした場合
        monkeypatch.setattr(discord_api, "_get_reaction_user_ids", fake_users)
        assert discord_api.get_approval_decision("c1", "m1", "tok", "123") == "reject"

    def test_other_users_reactions_are_ignored(self, monkeypatch):
        """他人のリアクションは無視（承認者ID不一致）。"""
        def fake_users(cid, mid, tok, emoji):
            return {"999"}  # bot自身・他人のID
        monkeypatch.setattr(discord_api, "_get_reaction_user_ids", fake_users)
        assert discord_api.get_approval_decision("c1", "m1", "tok", "123") == "pending"

    def test_api_error_is_error_not_pending(self, monkeypatch):
        """取得失敗は「未承認」でなく「error」（fail-closed・取得失敗≠未承認）。"""
        def raise_err(cid, mid, tok, emoji):
            raise discord_api.DiscordAPIError("429")
        monkeypatch.setattr(discord_api, "_get_reaction_user_ids", raise_err)
        assert discord_api.get_approval_decision("c1", "m1", "tok", "123") == "error"

    def test_bot_own_reaction_is_ignored(self, monkeypatch):
        """bot初期👍（approverと異なるID）は構造的に除外=単体でもpending。"""
        def fake_users(cid, mid, tok, emoji):
            return {"bot_id_999"}
        monkeypatch.setattr(discord_api, "_get_reaction_user_ids", fake_users)
        assert discord_api.get_approval_decision("c1", "m1", "tok", "123") == "pending"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_discord_api.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: FAIL（ModuleNotFoundError: No module named 'discord_api'）

- [ ] **Step 3: discord_api.pyを実装**

```python
#!/usr/bin/env python3
"""discord_api.py — Discord REST API薄ラッパー（Bot Token認証・常駐プロセスなし）。

X自動化lib/discord_client.pyと同型設計（zenn側に独立配置・リポジトリ間importはしない）。
承認判定は「承認者ID照合方式」: approver_user_idがリアクションを付けたかのみ判定するため、
bot自身の初期リアクション（承認者と異なるID）は構造的に除外される。
"""
from __future__ import annotations

import urllib.parse

import requests

API_BASE = "https://discord.com/api/v10"
REACTION_APPROVE = "\U0001F44D"  # 👍
REACTION_REJECT = "\U0001F44E"  # 👎

EMOJI_NAMES = {
    "thumbsup": "approve", ":+1:": "approve", REACTION_APPROVE: "approve",
    "thumbsdown": "reject", ":-1:": "reject", REACTION_REJECT: "reject",
}


class DiscordAPIError(RuntimeError):
    """Discord API呼び出し失敗（401/403/429/5xx/通信エラー）。"""


def _headers(bot_token: str) -> dict:
    return {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}


def normalize_emoji(emoji: str) -> str:
    """絵文字表記をapprove/reject/その他に正規化する（unicode codepoint・Discord名両対応）。"""
    return EMOJI_NAMES.get(emoji, emoji)


def resolve_channel_id_from_webhook(webhook_url: str) -> str:
    """webhook URLからchannel_idを解決する（webhookオブジェクトにchannel_idフィールド実在）。"""
    try:
        resp = requests.get(webhook_url, timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"webhook取得中に通信エラー: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordAPIError(f"webhook取得失敗: {resp.status_code}")
    channel_id = resp.json().get("channel_id")
    if not channel_id:
        raise DiscordAPIError("webhook応答にchannel_idが無い")
    return str(channel_id)


def send_message(channel_id: str, bot_token: str, content: str) -> str:
    """メッセージを送信しmessage_idを返す。401/403はDiscordAPIError（呼び出し側でDiscord通知）。"""
    try:
        resp = requests.post(
            f"{API_BASE}/channels/{channel_id}/messages",
            json={"content": content}, headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"メッセージ送信中に通信エラー: {exc}") from exc
    if resp.status_code in (401, 403, 429, 500, 502, 503):
        raise DiscordAPIError(f"メッセージ送信失敗: {resp.status_code} {resp.text[:200]}")
    if resp.status_code != 200:
        raise DiscordAPIError(f"メッセージ送信失敗: {resp.status_code} {resp.text[:200]}")
    return str(resp.json()["id"])


def add_reaction(channel_id: str, message_id: str, bot_token: str, emoji: str) -> None:
    """メッセージにリアクションを初期付与する（自分のメッセージにも付与可能）。"""
    encoded = urllib.parse.quote(emoji)
    try:
        resp = requests.put(
            f"{API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"リアクション付与中に通信エラー: {exc}") from exc
    if resp.status_code not in (200, 204):
        raise DiscordAPIError(f"リアクション付与失敗: {resp.status_code} {resp.text[:200]}")


def message_exists(channel_id: str, message_id: str, bot_token: str) -> bool:
    """メッセージが存在するか確認（404=削除済み→False・403等はDiscordAPIError）。"""
    try:
        resp = requests.get(
            f"{API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"メッセージ確認中に通信エラー: {exc}") from exc
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    raise DiscordAPIError(f"メッセージ確認失敗: {resp.status_code} {resp.text[:200]}")


def _get_reaction_user_ids(channel_id: str, message_id: str, bot_token: str,
                           normalized: str) -> set[str]:
    """指定emojiのリアクションを付けたuser_idの集合を取得する。

    normalized は "approve"/"reject" を想定（内部でcodepointへ戻す）。
    limit=100で1ページ取得（このチャンネルの反応者は少数想定・それでも
    after指定でページ送りは実装しない=超過時は全取得を諦めて空集合を返さず
    DiscordAPIErrorを投げる「取得失敗≠未承認」設計）。
    """
    emoji_code = {"approve": REACTION_APPROVE, "reject": REACTION_REJECT}[normalized]
    encoded = urllib.parse.quote(emoji_code)
    url = (f"{API_BASE}/channels/{channel_id}/messages/{message_id}"
           f"/reactions/{encoded}?limit=100")
    try:
        resp = requests.get(url, headers=_headers(bot_token), timeout=15)
    except requests.exceptions.RequestException as exc:
        raise DiscordAPIError(f"リアクション取得中に通信エラー: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordAPIError(f"リアクション取得失敗: {resp.status_code} {resp.text[:200]}")
    users = resp.json()
    if len(users) >= 100:
        # ページ上限に達した=取得漏れの可能性 → fail-closed
        raise DiscordAPIError("リアクション100件超=ページング未対応・取得を諦める（fail-closed）")
    return {str(u["id"]) for u in users}


def get_approval_decision(channel_id: str, message_id: str, bot_token: str,
                          approver_user_id: str) -> str:
    """承認判定を返す。"approve"/"reject"/"pending"/"error"。

    - 承認者ID照合方式: approver_user_idが付けたリアクションのみ判定対象
      （botの初期リアクション・他人のリアクションは構造的に除外される）
    - 👎優先（approverが両方付けた場合はreject=安全側）
    - API取得失敗は"error"（空集合≠未承認・fail-closed）
    """
    try:
        reject_users = _get_reaction_user_ids(channel_id, message_id, bot_token, "reject")
        if approver_user_id in reject_users:
            return "reject"
        approve_users = _get_reaction_user_ids(channel_id, message_id, bot_token, "approve")
        if approver_user_id in approve_users:
            return "approve"
        return "pending"
    except DiscordAPIError:
        return "error"


def send_error_notification(webhook_url: str, text: str) -> None:
    """checker失敗時のDiscordエラー通知（webhook経由・best effort・失敗しても例外を投げない）。"""
    try:
        requests.post(webhook_url, json={"content": f"⚠️ approve-checkエラー: {text}"},
                      timeout=15)
    except requests.exceptions.RequestException:
        pass
```

- [ ] **Step 4: テストが合格することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_discord_api.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: PASS（全テスト緑・EXIT=0）

- [ ] **Step 5: commit**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
git add scripts/discord_api.py tests/test_discord_api.py
git commit-scoped -m "feat: discord_api.py新設（Discord REST薄ラッパー・承認者ID照合・絵文字正規化・fail-closed）" -- scripts/discord_api.py tests/test_discord_api.py
```

---

### Task 2: approve_checker.py — 判定ロジック本体（TDD）

**Files:**
- Create: `scripts/approve_checker.py`
- Test: `tests/test_approve_checker.py`

**状態ファイル仕様**（`docs/discord_messages.json`）:

```json
{
  "issue_number_str": {
    "message_id": "...", "channel_id": "...",
    "content_hash": "sha256hex",
    "status": "pending|rejected|reapproval",
    "attempts": 0,
    "last_notify_date": "2026-11-26",
    "created_at": "2026-11-26T04:00:00+09:00"
  }
}
```

- [ ] **Step 1: 失敗テストを書く**

```python
"""tests/test_approve_checker.py — approve_checker.pyの単体テスト（API呼び出しはモック）。"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import approve_checker as ac
import pytest


@pytest.fixture
def entries():
    return {
        "106": {"message_id": "m106", "channel_id": "c1",
                "content_hash": "abc", "status": "pending",
                "attempts": 0, "last_notify_date": "2026-11-26",
                "created_at": "2026-11-26T04:00:00+09:00"},
        "107": {"message_id": "m107", "channel_id": "c1",
                "content_hash": "abc", "status": "rejected",
                "attempts": 1, "last_notify_date": "2026-11-25",
                "created_at": "2026-11-25T04:00:00+09:00"},
    }


class TestContentHash:
    def test_frontmatter_excluded(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: X\n---\n\n## 本文A\n", encoding="utf-8")
        expect = hashlib.sha256("\n\n## 本文A\n".encode("utf-8")).hexdigest()
        assert ac.content_hash(str(p)) == expect

    def test_body_change_detected(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: X\n---\n\n## 本文A\n", encoding="utf-8")
        h1 = ac.content_hash(str(p))
        p.write_text("---\ntitle: X\n---\n\n## 本文B\n", encoding="utf-8")
        assert ac.content_hash(str(p)) != h1

    def test_frontmatter_change_ignored(self, tmp_path):
        """frontmatterのみの変更（emoji等）はhash不変（本文SHA-256・frontmatter除外）。"""
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: X\nemoji: 📊\n---\n\n## 本文A\n", encoding="utf-8")
        h1 = ac.content_hash(str(p))
        p.write_text("---\ntitle: X\nemoji: 📝\n---\n\n## 本文A\n", encoding="utf-8")
        assert ac.content_hash(str(p)) == h1


class TestLoopLimit:
    def test_at_limit_is_manual_downgrade(self, entries):
        """attempts>=3で「manual」判定（自動転送せず手動確認降格）。"""
        entries["106"]["attempts"] = 3
        assert ac.is_loop_exceeded(entries["106"]) is True

    def test_under_limit_is_ok(self, entries):
        assert ac.is_loop_exceeded(entries["106"]) is False


class TestRecoverRejected:
    def test_rejected_with_new_thumb_up_recovers(self, monkeypatch, entries):
        """rejected状態+再👍 → 復旧（再オープン+転送）。"""
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        entry = entries["107"]
        assert ac.handle_entry(entry, issue_num=107, pat="p", repo="r") == "recover"

    def test_rejected_without_thumb_up_stays(self, monkeypatch, entries):
        monkeypatch.setattr(ac, "get_decision", lambda e: "pending")
        entry = entries["107"]
        assert ac.handle_entry(entry, issue_num=107, pat="p", repo="r") == "pending"


class TestCleanup:
    def test_30day_old_entries_removed(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        fresh = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        entries = {
            "1": {"created_at": old, "status": "pending"},
            "2": {"created_at": fresh, "status": "pending"},
            "3": {"created_at": old, "status": "rejected"},
        }
        kept = ac.cleanup_expired(entries)
        assert "1" not in kept
        assert "2" in kept
        assert "3" not in kept  # rejected保持は30日で清掃（spec仕様）

    def test_malformed_entry_kept_safe(self):
        entries = {"9": {"status": "pending"}}  # created_at欠落
        assert ac.cleanup_expired(entries) == entries


class TestAtomicSave:
    def test_save_creates_valid_json(self, tmp_path):
        path = str(tmp_path / "discord_messages.json")
        ac.save_entries(path, {"1": {"status": "pending"}})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"1": {"status": "pending"}}

    def test_load_missing_file_returns_empty(self, tmp_path):
        assert ac.load_entries(str(tmp_path / "no.json")) == {}
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_approve_checker.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: FAIL（No module named 'approve_checker'）

- [ ] **Step 3: approve_checker.pyを実装**

```python
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
    from notifier import load_meta_title  # タイトル取得（Task 3で実装）
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

    # 1. 404=メッセージ削除 → エントリ削除
    exists = discord_api.message_exists(entry["channel_id"], entry["message_id"],
                                        os.environ["DISCORD_BOT_TOKEN"])
    if not exists:
        return "deleted"

    # 2. 判定（取得失敗はfail-closed・何もせずerror通知）
    decision = get_decision(entry)
    if decision == "error":
        discord_api.send_error_notification(
            webhook_url, f"issue#{issue_num}: リアクション取得失敗（API・権限の疑い）")
        return "error"

    status = entry.get("status", "pending")

    # 3. rejected状態: 再👍で自動復旧（issue再オープン+転送）
    if status == "rejected":
        if decision == "approve":
            reopen_issue(pat, issue_num)
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
            if entry.get("last_notify_date") == today:
                return "renotify_skipped"  # 1日1回上限
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
            entry["last_notify_date"] = today
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

    # 7. reject → issue却下Close
    if decision == "reject":
        close_issue_reject(pat, issue_num)
        return "reject"

    return "pending"


def git_commit_push(message: str) -> None:
    """json変更をcommit+push（pull --rebaseで衝突回避・衝突時はGitHub API再検証は省略形で次回実行）。"""
    subprocess.run(["git", "pull", "--rebase"], cwd=REPO_ROOT, check=False)
    subprocess.run(["git", "add", os.path.relpath(ENTRIES_PATH, REPO_ROOT)],
                   cwd=REPO_ROOT, check=True)
    r = subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT,
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return  # 変更なし等
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=False)


def main() -> int:
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    approver_user_id = os.environ["DISCORD_APPROVER_USER_ID"]
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
        except discord_api.DiscordAPIError as exc:
            discord_api.send_error_notification(webhook_url, f"issue#{issue_num}: {exc}")
            result = "error"
        actions[key] = result
        if result in ("forwarded", "reject", "recover", "deleted"):
            entries.pop(key)  # 転送成功・却下・復旧・削除でエントリ除去（二重転送防止）

    entries = cleanup_expired(entries)

    if actions:
        save_entries(ENTRIES_PATH, entries)
        git_commit_push("chore: approve-check状態更新（自動）")
        print(json.dumps(actions, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**注意（実装時の整合チェック）**: `entry`には`slug`をnotifier側で記録しておく（Task 3のjson記録にslugを追加する）。上記コードの`entry.get("slug")`ガードは旧データ互換。

- [ ] **Step 4: テストが合格することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_approve_checker.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: PASS（EXIT=0）

- [ ] **Step 5: commit**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
git add scripts/approve_checker.py tests/test_approve_checker.py
git commit-scoped -m "feat: approve_checker.py新設（承認者ID照合・hash照合・ループ上限3回・rejected再👍自動復旧・fail-closed）" -- scripts/approve_checker.py tests/test_approve_checker.py
```

---

### Task 3: notifier.py拡張 — bot送信化+json記録

**Files:**
- Modify: `scripts/notifier.py`
- Test: `tests/test_notifier.py`（新規）

- [ ] **Step 1: 失敗テストを書く**

```python
"""tests/test_notifier.py — notifier.py bot送信化の単体テスト（API呼び出しはモック）。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import notifier
import pytest


class TestBuildApprovalContent:
    def test_content_contains_guide_and_recover(self):
        c = notifier.build_approval_content("スラグ", "タイトルX")
        assert "👍" in c and "却下" in c
        assert "再度👍" in c  # 誤却下復旧手順
        assert "90分" in c   # 公開所要時間の期待設定

    def test_no_secret_in_content(self):
        c = notifier.build_approval_content("スラグ", "タイトルX")
        assert "token" not in c.lower()


class TestBuildEntry:
    def test_entry_has_slug_hash_and_status(self, tmp_path):
        art = tmp_path / "my-slug.md"
        art.write_text("---\ntitle: T\n---\n\n本文\n", encoding="utf-8")
        from approve_checker import content_hash
        e = notifier.build_entry("my-slug", str(art), "chan1", "msg1")
        assert e["status"] == "pending"
        assert e["slug"] == "my-slug"
        assert e["channel_id"] == "chan1"
        assert e["message_id"] == "msg1"
        assert e["content_hash"] == content_hash(str(art))
        assert e["attempts"] == 0


class TestSendApprovalMessage:
    def test_sends_and_records_entry(self, monkeypatch, tmp_path):
        calls = []

        def fake_send(cid, tok, content):
            calls.append(content)
            return "mid_new"

        def fake_react(cid, mid, tok, emoji):
            calls.append(("react", emoji))

        monkeypatch.setattr(notifier._api, "send_message", fake_send)
        monkeypatch.setattr(notifier._api, "add_reaction", fake_react)
        monkeypatch.setattr(notifier, "resolve_channel_id", lambda w: "chan1")

        entries_path = str(tmp_path / "discord_messages.json")
        entry = notifier.send_approval_message(
            {"slug": "my-slug"}, entries_path=entries_path,
            bot_token="tok", webhook_url="https://wh.example",
            article_path=str(tmp_path / "my-slug.md"), issue_num=106)
        assert entry["message_id"] == "mid_new"
        assert entry["status"] == "pending"
        assert len(calls) >= 2  # 送信+リアクション付与
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_notifier.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: FAIL（AttributeError: module 'notifier' has no attribute 'build_approval_content'）

- [ ] **Step 3: notifier.pyを拡張（既存関数は残す・bot送信系を追加）**

```python
# notifier.py の末尾に以下を追加（既存の load_meta/send_discord/create_issue/main は変更しない）

import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord_api as _api


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
```

- [ ] **Step 3.5: notifier.py冒頭のimportに追加**

```python
# 既存import群の後に追加:
from datetime import datetime, timezone
```

- [ ] **Step 4: テストが合格することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_notifier.py tests/test_approve_checker.py tests/test_discord_api.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: PASS（EXIT=0）

- [ ] **Step 5: discover.ymlに承認メッセージ送信ステップを追加**

`Notify (Discord + Issue)`ステップ（notifier.py main実行）の**後**に追加:

```yaml
      - name: Send approval message (Discord bot + json record)
        if: always() && steps.check.outputs.skip != 'true'
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python scripts/notifier_send_approval.py
```

- [ ] **Step 6: notifier_send_approval.pyを新設（workflow用の薄いラッパー・envから発火）**

```python
#!/usr/bin/env python3
"""notifier_send_approval.py — discover.yml用ラッパー: issue番号を取得し承認メッセージを送信。

issue番号は notifier.py の create_issue が返すが、現行実装はprintのみのため
issue一覧から直近のslug一致issueを検索する（冪等・重複送信はjson上書きで自然回避）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import notifier

REPO_FULL = "fukukei23/zenn"


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
    bot_token = os.environ["DISCORD_BOT_TOKEN"]
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not bot_token or not webhook_url:
        print("DISCORD_BOT_TOKEN/DISCORD_WEBHOOK_URL未設定 → 承認メッセージ送信をスキップ")
        return 0
    issue_num = find_issue_number(token, meta["slug"])
    if issue_num is None:
        print("対応するissueが見つからずスキップ")
        return 0
    entries_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "docs", "discord_messages.json")
    article_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "articles", f"{meta['slug']}.md")
    entry = notifier.send_approval_message(meta, entries_path, bot_token,
                                           webhook_url, article_path, issue_num)
    print(f"approval message sent: issue#{issue_num} msg={entry['message_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: jsonをgit追跡対象にする（docs/discord_messages.json 初期作成+commit）**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
echo '{}' > docs/discord_messages.json
git add scripts/notifier.py scripts/notifier_send_approval.py tests/test_notifier.py .github/workflows/discover.yml docs/discord_messages.json
git commit-scoped -m "feat: notifier.py bot送信化（👍初期付与・json記録・channel_id解決）+discover.yml承認メッセージ送信ステップ" -- scripts/notifier.py scripts/notifier_send_approval.py tests/test_notifier.py .github/workflows/discover.yml docs/discord_messages.json
```

---

### Task 4: reapprover.py — 品質ゲート修正時の再承認メッセージ再送

**Files:**
- Create: `scripts/reapprover.py`
- Test: `tests/test_reapprover.py`

- [ ] **Step 1: 失敗テストを書く**

```python
"""tests/test_reapprover.py — reapprover.pyの単体テスト。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import reapprover as ra
import pytest


class TestBuildReapprovalContent:
    def test_contains_diff_summary_and_reason(self):
        c = ra.build_reapproval_content("my-slug", "タイトル",
                                        [("元の文A", "修正後の文A", "表記ゆれ")])
        assert "再承認" in c
        assert "修正後の文A" in c
        assert "表記ゆれ" in c
        assert "👍" in c


class TestUpdateEntryForReapproval:
    def test_rehashes_and_increments_attempt(self, tmp_path):
        entries = {"106": {"slug": "my-slug", "message_id": "m1",
                           "channel_id": "c1", "content_hash": "old",
                           "status": "reapproval", "attempts": 0,
                           "last_notify_date": "2026-11-26",
                           "created_at": "2026-11-26T00:00:00+00:00"}}
        art = tmp_path / "my-slug.md"
        art.write_text("---\ntitle: T\n---\n\n修正後本文\n", encoding="utf-8")
        entries_path = str(tmp_path / "discord_messages.json")
        with open(entries_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)
        from approve_checker import content_hash, load_entries
        new_entry = ra.update_entry_for_reapproval(
            entries_path, "106", article_path=str(art))
        assert new_entry["content_hash"] == content_hash(str(art))
        assert new_entry["attempts"] == 1  # 再承認要求発行時のみインクリメント


class TestLoopExceeded:
    def test_3_attempts_returns_none(self, tmp_path):
        entries = {"106": {"slug": "s", "message_id": "m", "channel_id": "c",
                           "content_hash": "h", "status": "reapproval",
                           "attempts": 3, "last_notify_date": "x",
                           "created_at": "2026-11-26T00:00:00+00:00"}}
        entries_path = str(tmp_path / "discord_messages.json")
        with open(entries_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)
        assert ra.update_entry_for_reapproval(
            entries_path, "106", article_path="/nonexistent") is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_reapprover.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: FAIL（No module named 'reapprover'）

- [ ] **Step 3: reapprover.pyを実装**

```python
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
        return 0
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
```

- [ ] **Step 4: テストが合格することを確認**

Run: `cd ~/projects/obsidian-ssot/50_PROJECTS/zenn && python3 -m pytest tests/test_reapprover.py -v 2>&1 | tail -3; echo EXIT=$?`
Expected: PASS（EXIT=0）

- [ ] **Step 5: commit**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
git add scripts/reapprover.py tests/test_reapprover.py
git commit-scoped -m "feat: reapprover.py新設（品質ゲート修正後の再承認メッセージ再送・修正後本文再hash・ループ上限）" -- scripts/reapprover.py tests/test_reapprover.py
```

---

### Task 5: approve-check.yml — workflow新設

**Files:**
- Create: `.github/workflows/approve-check.yml`

- [ ] **Step 1: workflowを作成**

```yaml
name: Approve Checker

on:
  schedule:
    - cron: '17 * * * *'   # 毎時17分（:00/:30回避・発火集中回避）
  workflow_dispatch: {}    # Phase 0実測用手動発火

permissions:
  contents: write
  issues: write

concurrency:
  group: approve-check
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r scripts/requirements.txt

      - name: Approve checker (reaction判定→PAT転送)
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_APPROVER_USER_ID: ${{ secrets.DISCORD_APPROVER_USER_ID }}
          GITHUB_PAT: ${{ secrets.PERSONAL_ACCESS_TOKEN }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: python scripts/approve_checker.py
```

- [ ] **Step 2: YAML構文検証（ローカル・python yamlでparse）**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/approve-check.yml')); print('YAML OK')"; echo EXIT=$?
```
Expected: `YAML OK`・EXIT=0

- [ ] **Step 3: commit**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
git add .github/workflows/approve-check.yml
git commit-scoped -m "feat: approve-check.yml新設（毎時リアクション判定→PAT転送・concurrency付き）" -- .github/workflows/approve-check.yml
```

---

### Task 6: publish.yml — ja_gate後の再送ステップ追加

**Files:**
- Modify: `.github/workflows/publish.yml`（ja_gateステップ後・45行目付近）

- [ ] **Step 1: 再送ステップを追加**

`Japanese quality gate (fix + approval loop)`ステップ（id: ja_gate）の直後に挿入:

```yaml
      - name: Re-send approval message (gate=fixed)
        if: steps.ja_gate.outputs.gate == 'fixed'
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
        run: python scripts/reapprover.py
```

- [ ] **Step 2: YAML構文検証**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml')); print('YAML OK')"; echo EXIT=$?
```
Expected: `YAML OK`・EXIT=0

- [ ] **Step 3: commit**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
git add .github/workflows/publish.yml
git commit-scoped -m "feat: publish.ymlにgate=fixed時の再承認メッセージ再送ステップを追加（トリガー条件・公開ロジックは不変）" -- .github/workflows/publish.yml
```

---

### Task 7: secrets登録+統合実測（Phase 0開始）

**Files:** 変更なし（GitHub側設定+実機検証）

- [ ] **Step 0: PATをfine-grainedへ新規発行（ふくけい手作業・約5分）**

GitHub Settings → Developer settings → Fine-grained personal access tokens → Generate new token:
- 対象リポジトリ: `fukukei23/zenn` のみ
- 権限: **Issues: Read and write** のみ（contents不要・workflow不要）
- 有効期限: 90日等（後述のPhase 0継続測定期間をカバー）
- 発行後の値をCCに渡す → CCが `.secrets.env` の `PERSONAL_ACCESS_TOKEN` と GitHub secrets を更新
  - 現行PAT（旧トークン）は無効化をふくけいがGitHub画面で実施
- ⚠️ 旧PATが別用途（他リポジトリ）で使われている場合は新規に別tokenを作る（削除しない・事前に `gh api user` で旧PATが動くことを確認済み）

- [ ] **Step 1: DISCORD_BOT_TOKENをGitHub secretsに登録**

```bash
source ~/.secrets.env
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
GH_TOKEN=$GH_TOKEN gh secret set DISCORD_BOT_TOKEN --body "$DISCORD_BOT_TOKEN"
GH_TOKEN=$GH_TOKEN gh secret set DISCORD_APPROVER_USER_ID --body "$DISCORD_APPROVER_USER_ID"
GH_TOKEN=$GH_TOKEN gh secret list 2>&1 | grep -E "DISCORD_BOT_TOKEN|DISCORD_APPROVER_USER_ID"
echo EXIT=$?
```
Expected: 2行がlist出力に現れる・EXIT=0

- [ ] **Step 2: 全テスト最終実行**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
python3 -m pytest tests/test_discord_api.py tests/test_approve_checker.py tests/test_notifier.py tests/test_reapprover.py tests/test_ja_quality_fix.py -q 2>&1 | tail -3; echo EXIT=$?
```
Expected: 全緑・EXIT=0

- [ ] **Step 3: push（workflow有効化を含む）**

```bash
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
git push origin master; echo EXIT=$?
```
Expected: push成功・EXIT=0

- [ ] **Step 4: Phase 0項目3（bot権限実測）開始 — workflow_dispatchでapprove-check手動実行**

```bash
source ~/.secrets.env
cd ~/projects/obsidian-ssot/50_PROJECTS/zenn
GH_TOKEN=$GH_TOKEN gh workflow run approve-check.yml 2>&1; echo EXIT=$?
```
Expected: EXIT=0（手動発火）→ 次にbot送信の実測は次のドラフト発火（日次discover）またはPhase 0手順書に従い実施

- [ ] **Step 5: Phase 0残項目の起票**

Phase 0項目1（E2E 5回実測+30日継続測定）・項目2（実転送1回・issue #107以降の最初のドラフトで実施）・項目5（再承認フロー実測・品質ゲート修正が実際に起きた最初の1件）は運用観察のため、
`00_SYSTEM/バックログ.md`へ `type:verification` ラベルで起票する（fail条件: 実転送1回でOWNER判定が通らない / E2E 90分超え2回以上 / 絵文字照合不一致）。

---

## 実装後の運用フロー（確認用）

```
日次discover.yml → issue+Discord承認メッセージ（👍初期付与付き）
→ ふくけい: 👍タップ
→ 毎時17分 approve-check.yml → 判定 → PAT転送 /approve
→ publish.yml発火 → ja_gate → 公開 → issue Close → Discord完了通知
→ 品質ゲート修正時: gate=fixed → reapprover.py再送 → 再タップ → 再転送（3回上限）
```
