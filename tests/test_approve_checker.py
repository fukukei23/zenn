"""tests/test_approve_checker.py — approve_checker.pyの単体テスト（API呼び出しはモック）。"""
import hashlib
import json
import os
import sys

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
        """rejected状態+再👍 → 復旧（再オープン+転送）。API副作用はモック遮断。"""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        monkeypatch.setattr(ac.discord_api, "message_exists", lambda cid, mid, tok: True)
        monkeypatch.setattr(ac, "reopen_issue", lambda pat, num: None)
        entry = entries["107"]
        assert ac.handle_entry(entry, issue_num=107, pat="p", webhook_url="") == "recover"

    def test_rejected_without_thumb_up_stays(self, monkeypatch, entries):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setattr(ac, "get_decision", lambda e: "pending")
        monkeypatch.setattr(ac.discord_api, "message_exists", lambda cid, mid, tok: True)
        entry = entries["107"]
        assert ac.handle_entry(entry, issue_num=107, pat="p", webhook_url="") == "pending"


class TestHandleEntryBranches:
    """handle_entryの残り分岐網羅（coverage欠落対策・全API副作用はモック遮断）。"""

    def _base_mocks(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setattr(ac.discord_api, "message_exists", lambda cid, mid, tok: True)

    def test_deleted_when_message_missing(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac.discord_api, "message_exists", lambda cid, mid, tok: False)
        entry = entries["106"]
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "deleted"

    def test_error_notifies_webhook(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        notified = []
        monkeypatch.setattr(ac, "get_decision", lambda e: "error")
        monkeypatch.setattr(
            ac.discord_api, "send_error_notification",
            lambda url, text: notified.append(text))
        entry = entries["106"]
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="wh") == "error"
        assert len(notified) == 1  # 取得失敗≠未承認・エラー通知1件

    def test_forwarded_on_approve(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        calls = []
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        monkeypatch.setattr(
            ac, "post_approve_transfer",
            lambda pat, num, mid, ts: calls.append(num))
        entry = entries["106"]
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "forwarded"
        assert calls == [106]  # PAT転送が1回・issue番号一致

    def test_forwarded_reapproval_increments_attempts(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        monkeypatch.setattr(ac, "post_approve_transfer", lambda pat, num, mid, ts: None)
        entry = entries["106"]
        entry["status"] = "reapproval"
        entry["attempts"] = 1
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "forwarded"
        assert entry["attempts"] == 2  # reapproval承認時のみインクリメント

    def test_reject_closes_issue(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        calls = []
        monkeypatch.setattr(ac, "get_decision", lambda e: "reject")
        monkeypatch.setattr(
            ac, "close_issue_reject", lambda pat, num: calls.append(num))
        entry = entries["106"]
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "reject"
        assert calls == [106]

    def test_loop_exceeded_skips_without_transfer(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        transferred = []
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        monkeypatch.setattr(
            ac, "post_approve_transfer",
            lambda pat, num, mid, ts: transferred.append(num))
        entry = entries["106"]
        entry["attempts"] = 3
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "loop_exceeded"
        assert transferred == []  # 上限超過時は転送しない

    def test_renotify_skipped_same_day(self, monkeypatch, entries, tmp_path):
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac, "get_decision", lambda e: "pending")
        sent = []
        monkeypatch.setattr(
            ac.discord_api, "send_message", lambda cid, tok, c: sent.append(c))
        (tmp_path / "articles").mkdir()
        art = tmp_path / "articles" / "my-slug.md"
        art.write_text("---\ntitle: T\n---\n\n新しい本文\n", encoding="utf-8")
        entry = entries["106"]
        entry["slug"] = "my-slug"
        entry["content_hash"] = "stale"
        from datetime import datetime, timezone
        entry["last_notify_date"] = datetime.now(timezone.utc).date().isoformat()
        ac.REPO_ROOT = str(tmp_path)
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "renotify_skipped"
        assert sent == []  # 1日1回上限・再送しない

    def test_renotified_on_hash_change(self, monkeypatch, entries, tmp_path):
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac, "get_decision", lambda e: "pending")
        mids = iter(["mid_re"])
        monkeypatch.setattr(
            ac.discord_api, "send_message", lambda cid, tok, c: next(mids))
        monkeypatch.setattr(ac.discord_api, "add_reaction", lambda cid, mid, tok, e: None)
        (tmp_path / "articles").mkdir()
        art = tmp_path / "articles" / "my-slug.md"
        art.write_text("---\ntitle: T\n---\n\n新しい本文\n", encoding="utf-8")
        entry = entries["106"]
        entry["slug"] = "my-slug"
        entry["content_hash"] = "stale"
        entry["last_notify_date"] = "2026-11-01"  # 当日ではない
        ac.REPO_ROOT = str(tmp_path)
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "renotified"
        assert entry["message_id"] == "mid_re"
        assert entry["status"] == "reapproval"
        assert entry["attempts"] == 1
        assert entry["content_hash"] == ac.content_hash(str(art))  # 修正後本文で再hash

    def test_approve_transfer_loop_exceeded_downgrade(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        notified = []
        monkeypatch.setattr(
            ac.discord_api, "send_error_notification",
            lambda url, text: notified.append(text))
        monkeypatch.setattr(ac, "post_approve_transfer", lambda pat, num, mid, ts: None)
        entry = entries["106"]
        entry["status"] = "reapproval"
        entry["attempts"] = 2  # 転送時++で3に到達=超過（ステップ4の早期returnを回避する境界値）
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="wh") == "loop_exceeded"
        assert len(notified) == 1  # 手動確認降格のDiscord通知

    def test_renotify_loop_exceeded_downgrade(self, monkeypatch, entries, tmp_path):
        """hash不一致再送時のattempts++後超過→降格通知（L196-198分岐）。"""
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac, "get_decision", lambda e: "pending")
        notified = []
        monkeypatch.setattr(
            ac.discord_api, "send_error_notification",
            lambda url, text: notified.append(text))
        sent = []
        monkeypatch.setattr(
            ac.discord_api, "send_message", lambda cid, tok, c: sent.append(c))
        (tmp_path / "articles").mkdir()
        art = tmp_path / "articles" / "my-slug.md"
        art.write_text("---\ntitle: T\n---\n\n新しい本文\n", encoding="utf-8")
        entry = entries["106"]
        entry["slug"] = "my-slug"
        entry["content_hash"] = "stale"
        entry["attempts"] = 2  # 再送時++で3に到達=超過
        entry["last_notify_date"] = "2026-11-01"
        ac.REPO_ROOT = str(tmp_path)
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="wh") == "loop_exceeded"
        assert sent == []  # 再送前に降格・メッセージは送らない
        assert len(notified) == 1

    def test_send_notify_message_updates_entry(self, monkeypatch, entries):
        """send_notify_message: 送信+👍付与+entry更新（L130-146）。"""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
        mids = iter(["mid_sn"])
        monkeypatch.setattr(
            ac.discord_api, "send_message", lambda cid, tok, c: next(mids))
        reacts = []
        monkeypatch.setattr(
            ac.discord_api, "add_reaction",
            lambda cid, mid, tok, e: reacts.append((mid, e)))
        entry = entries["106"]
        mid = ac.send_notify_message(entry, "my-slug", "タイトル", "tok", "u", "wh")
        assert mid == "mid_sn"
        assert entry["message_id"] == "mid_sn"
        assert entry["last_notify_date"] != ""
        assert reacts == [("mid_sn", ac.discord_api.REACTION_APPROVE)]  # 👍初期付与


class TestMainEmpty:
    def test_main_empty_entries_returns_zero(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "t")
        monkeypatch.setenv("DISCORD_APPROVER_USER_ID", "u")
        monkeypatch.setenv("GITHUB_PAT", "p")
        monkeypatch.setattr(ac, "load_entries", lambda path=None: {})
        assert ac.main() == 0


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
