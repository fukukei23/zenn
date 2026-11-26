"""tests/test_discord_api.py — discord_api.pyの単体テスト（モック使用・API呼び出しなし）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import discord_api


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
