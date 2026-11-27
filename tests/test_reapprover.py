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

    def test_missing_entry_returns_none(self, tmp_path):
        entries_path = str(tmp_path / "discord_messages.json")
        with open(entries_path, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False)
        assert ra.update_entry_for_reapproval(
            entries_path, "999", article_path="/nonexistent") is None


class TestBuildContentFixesLimit:
    def test_fixes_capped_at_five(self):
        fixes = [(f"元{i}", f"修{i}", f"理由{i}") for i in range(7)]
        c = ra.build_reapproval_content("s", "t", fixes)
        assert "修6" not in c  # 7件目は出ない（上限5）
        assert "修4" in c      # 5件目は出る


class TestResolveSlugFromIssue:
    def test_slug_extracted_from_body(self, monkeypatch):
        class Resp:
            status_code = 200

            def json(self):
                return {"body": "本文 <!-- slug: my-slug --> 続き"}

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            ra.requests, "get", lambda *a, **kw: Resp())
        assert ra.resolve_slug_from_issue("tok", "106") == "my-slug"

    def test_no_marker_returns_empty(self, monkeypatch):
        class Resp:
            status_code = 200

            def json(self):
                return {"body": "マーカーなし本文"}

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            ra.requests, "get", lambda *a, **kw: Resp())
        assert ra.resolve_slug_from_issue("tok", "106") == ""


class TestMainSlugFallback:
    def test_meta_missing_resolves_slug_from_issue(self, monkeypatch, tmp_path):
        """publish.yml runnerはarticle_meta.jsonが無い → issue本文からslug解決（MLR r1採用）。"""
        entries = {"106": {"slug": "s", "message_id": "old", "channel_id": "c1",
                           "content_hash": "old", "status": "reapproval",
                           "attempts": 0, "last_notify_date": "x",
                           "created_at": "2026-11-26T00:00:00+00:00"}}
        entries_path = tmp_path / "discord_messages.json"
        entries_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
        monkeypatch.setenv("ISSUE_NUMBER", "106")
        monkeypatch.setenv("GITHUB_TOKEN", "gtok")
        mids = iter(["mid_fb"])
        monkeypatch.setattr(
            ra.discord_api, "send_message", lambda cid, tok, c: next(mids))
        monkeypatch.setattr(
            ra.discord_api, "add_reaction", lambda cid, mid, tok, e: None)
        monkeypatch.setattr(ra, "ENTRIES_PATH", str(entries_path))
        monkeypatch.setattr(ra, "REPO_ROOT", str(tmp_path))
        resolved = {}
        monkeypatch.setattr(
            ra, "resolve_slug_from_issue",
            lambda tok, key: resolved.update(key=key) or "fallback-slug")
        assert ra.main() == 0
        assert resolved.get("key") == "106"  # issue番号でslug解決した
        entries2 = json.load(open(entries_path, encoding="utf-8"))
        assert entries2["106"]["message_id"] == "mid_fb"


class TestMain:
    def test_main_sends_and_updates_entry(self, monkeypatch, tmp_path):
        """reapprover main正常系: entry更新+送信+👍付与（L57-85）。"""
        entries = {"106": {"slug": "s", "message_id": "old", "channel_id": "c1",
                           "content_hash": "old", "status": "reapproval",
                           "attempts": 0, "last_notify_date": "x",
                           "created_at": "2026-11-26T00:00:00+00:00"}}
        entries_path = tmp_path / "discord_messages.json"
        entries_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "article_meta.json").write_text(
            json.dumps({"slug": "s", "title": "T"}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
        monkeypatch.setenv("ISSUE_NUMBER", "106")
        mids = iter(["mid_ra"])
        monkeypatch.setattr(
            ra.discord_api, "send_message", lambda cid, tok, c: next(mids))
        reacts = []
        monkeypatch.setattr(
            ra.discord_api, "add_reaction",
            lambda cid, mid, tok, e: reacts.append(e))
        monkeypatch.setattr(ra, "ENTRIES_PATH", str(entries_path))
        monkeypatch.setattr(ra, "REPO_ROOT", str(tmp_path))
        assert ra.main() == 0
        entries2 = json.load(open(entries_path, encoding="utf-8"))
        assert entries2["106"]["message_id"] == "mid_ra"  # 送信後にentry更新
        assert reacts == [ra.discord_api.REACTION_APPROVE]

    def test_main_no_issue_number_fails_fast(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
        monkeypatch.delenv("ISSUE_NUMBER", raising=False)
        assert ra.main() == 1  # サイレント0ではなくfail-fast（MLR指摘採用）
