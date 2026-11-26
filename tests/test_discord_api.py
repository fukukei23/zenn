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


class _Resp:
    """requests.Responseの最小モック（status_code/json/textのみ使用）。"""

    def __init__(self, status_code, payload=None, text="err"):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class TestResolveChannelId:
    def test_200_with_channel_id(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get", lambda url, timeout=None: _Resp(200, {"channel_id": 42}))
        assert discord_api.resolve_channel_id_from_webhook("https://wh") == "42"

    def test_non_200_raises(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get", lambda url, timeout=None: _Resp(404))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api.resolve_channel_id_from_webhook("https://wh")

    def test_missing_channel_id_raises(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get", lambda url, timeout=None: _Resp(200, {}))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api.resolve_channel_id_from_webhook("https://wh")

    def test_request_exception_raises(self, monkeypatch):
        def raise_conn(url, timeout):
            raise discord_api.requests.exceptions.RequestException("conn refused")
        monkeypatch.setattr(discord_api.requests, "get", raise_conn)
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api.resolve_channel_id_from_webhook("https://wh")


class TestSendMessage:
    def test_200_returns_id(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "post",
            lambda url, json=None, headers=None, timeout=None: _Resp(200, {"id": "mid9"}))
        assert discord_api.send_message("c1", "tok", "hello") == "mid9"

    def test_401_raises(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "post",
            lambda url, json=None, headers=None, timeout=None: _Resp(401, text="unauthorized"))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api.send_message("c1", "tok", "hello")


class TestAddReaction:
    def test_204_ok(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "put",
            lambda url, headers=None, timeout=None: _Resp(204))
        discord_api.add_reaction("c1", "m1", "tok", "👍")

    def test_non_2xx_raises(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "put",
            lambda url, headers=None, timeout=None: _Resp(500, text="boom"))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api.add_reaction("c1", "m1", "tok", "👍")


class TestMessageExists:
    def test_200_true(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(200))
        assert discord_api.message_exists("c1", "m1", "tok") is True

    def test_404_false(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(404))
        assert discord_api.message_exists("c1", "m1", "tok") is False

    def test_403_raises(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(403, text="forbidden"))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api.message_exists("c1", "m1", "tok")


class TestGetReactionUserIds:
    def test_200_returns_set(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(200, {"dummy": None}))
        # jsonはlistを返すべきだがモックはdict→ここでは素通しを確認するためlist版を別途
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(200, [{"id": "1"}, {"id": "2"}]))
        assert discord_api._get_reaction_user_ids("c1", "m1", "tok", "approve") == {"1", "2"}

    def test_over_100_fail_closed(self, monkeypatch):
        users = [{"id": str(i)} for i in range(100)]
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(200, users))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api._get_reaction_user_ids("c1", "m1", "tok", "approve")

    def test_non_200_raises(self, monkeypatch):
        monkeypatch.setattr(
            discord_api.requests, "get",
            lambda url, headers=None, timeout=None: _Resp(429, text="rate"))
        import pytest
        with pytest.raises(discord_api.DiscordAPIError):
            discord_api._get_reaction_user_ids("c1", "m1", "tok", "reject")


class TestSendErrorNotification:
    def test_never_raises(self, monkeypatch):
        def raise_conn(url, json=None, timeout=None):
            raise discord_api.requests.exceptions.RequestException("net down")
        monkeypatch.setattr(discord_api.requests, "post", raise_conn)
        discord_api.send_error_notification("https://wh", "test")  # 例外を投げないことが仕様
