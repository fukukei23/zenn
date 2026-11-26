"""tests/test_reapprover.py — reapprover.pyの単体テスト。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import reapprover as ra


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
        from approve_checker import content_hash
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
