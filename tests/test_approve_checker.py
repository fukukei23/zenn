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
