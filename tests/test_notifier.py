"""tests/test_notifier.py — notifier.py bot送信化の単体テスト（API呼び出しはモック）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import notifier


class TestBuildApprovalContent:
    def test_content_contains_guide_and_recover(self):
        c = notifier.build_approval_content("スラグ", "タイトルX")
        assert "👍" in c and "却下" in c
        assert "再度 👍" in c  # 誤却下復旧手順
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

        art = tmp_path / "my-slug.md"  # build_entry→content_hashの読込対象（実在必須）
        art.write_text("---\ntitle: T\n---\n\n本文\n", encoding="utf-8")
        entries_path = str(tmp_path / "discord_messages.json")
        entry = notifier.send_approval_message(
            {"slug": "my-slug"}, entries_path=entries_path,
            bot_token="tok", webhook_url="https://wh.example",
            article_path=str(art), issue_num=106)
        assert entry["message_id"] == "mid_new"
        assert entry["status"] == "pending"
        assert len(calls) >= 2  # 送信+リアクション付与
