"""tests/test_notifier_send_approval.py — notifier_send_approval.pyの単体テスト（API呼び出しはモック）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import notifier_send_approval as nsa


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class TestFindIssueNumber:
    def test_slug_match_returns_number(self, monkeypatch):
        resp = _Resp([{"number": 107, "body": "本文 <!-- slug: my-slug -->"},
                      {"number": 106, "body": "本文 <!-- slug: other -->"}])
        monkeypatch.setattr(nsa.requests, "get", lambda *a, **kw: resp)
        assert nsa.find_issue_number("tok", "my-slug") == 107

    def test_no_match_returns_none(self, monkeypatch):
        resp = _Resp([{"number": 106, "body": "本文 <!-- slug: other -->"}])
        monkeypatch.setattr(nsa.requests, "get", lambda *a, **kw: resp)
        assert nsa.find_issue_number("tok", "missing") is None


class TestMain:
    def test_no_meta_returns_zero(self, monkeypatch):
        monkeypatch.setattr(nsa.notifier, "load_meta", lambda: None)
        assert nsa.main() == 0

    def test_missing_bot_token_skips(self, monkeypatch):
        monkeypatch.setattr(nsa.notifier, "load_meta", lambda: {"slug": "s"})
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        assert nsa.main() == 0  # 未設定スキップ（送信しない）

    def test_meta_issue_number_preferred(self, monkeypatch, tmp_path):
        """meta["issue_number"]優先・API検索を呼ばない（2026-11-26実装適応）。"""
        monkeypatch.setattr(nsa.notifier, "load_meta",
                            lambda: {"slug": "my-slug", "issue_number": 105})
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "b")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://wh")
        called = {}
        monkeypatch.setattr(nsa, "find_issue_number", lambda tok, slug: called.setdefault("api", True))
        art_path = str(tmp_path / "my-slug.md")
        open(art_path, "w", encoding="utf-8").write("---\ntitle: T\n---\n\n本文\n")
        monkeypatch.setattr(
            nsa.notifier, "send_approval_message",
            lambda meta, ep, bt, wu, ap, num: called.update(num=num) or {"message_id": "m1"})
        monkeypatch.setattr(nsa, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr("os.path.join", os.path.join)
        # main内部のentries_path/article_pathはREPO_ROOT結合 → REPO_ROOTをtmpに差し替え済み
        nsa.main()
        assert called.get("num") == 105  # meta優先で105・API検索は未呼び
        assert "api" not in called
