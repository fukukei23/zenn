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
        """rejected状態+再👍 → 復旧（再オープン+即転送・specどおり）。API副作用はモック遮断。"""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setattr(ac, "get_decision", lambda e: "approve")
        monkeypatch.setattr(ac.discord_api, "message_exists", lambda cid, mid, tok: True)
        monkeypatch.setattr(ac, "reopen_issue", lambda pat, num: None)
        transferred = []
        monkeypatch.setattr(
            ac, "post_approve_transfer",
            lambda pat, num, mid, ts: transferred.append(num))
        entry = entries["107"]
        assert ac.handle_entry(entry, issue_num=107, pat="p", webhook_url="") == "recover"
        assert transferred == [107]  # 復旧時に即転送（MLR指摘採用・転送なしpopの欠陥修正）

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

    def test_reject_closes_issue_and_keeps_entry_rejected(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        calls = []
        monkeypatch.setattr(ac, "get_decision", lambda e: "reject")
        monkeypatch.setattr(
            ac, "close_issue_reject", lambda pat, num: calls.append(num))
        entry = entries["106"]
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "reject"
        assert calls == [106]
        assert entry["status"] == "rejected"  # 復旧可能状態を保持（MLR指摘採用・即popの欠陥修正）

    def test_deleted_notifies_issue_before_removal(self, monkeypatch, entries):
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac.discord_api, "message_exists", lambda cid, mid, tok: False)
        notified = []
        monkeypatch.setattr(
            ac, "notify_message_deleted", lambda pat, num: notified.append(num))
        entry = entries["106"]
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "deleted"
        assert notified == [106]  # サイレント消失防止コメント（MLR指摘採用）

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
        entry["renotified_date"] = datetime.now(timezone.utc).date().isoformat()
        monkeypatch.setattr(ac, "REPO_ROOT", str(tmp_path))
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "renotify_skipped"
        assert sent == []  # 再通知1日1回上限（renotified_date基準・MLR r2 GLM指摘採用）

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
        monkeypatch.setattr(ac, "REPO_ROOT", str(tmp_path))
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "renotified"
        assert entry["message_id"] == "mid_re"
        assert entry["status"] == "reapproval"
        assert entry["attempts"] == 1
        assert entry["content_hash"] == ac.content_hash(str(art))  # 修正後本文で再hash
        assert entry["renotified_date"] != ""  # 再通知日が記録される

    def test_renotified_same_day_as_first_notify(self, monkeypatch, entries, tmp_path):
        """初回通知当日のhash不一致でも再通知が通る（renotified_date未記録・MLR r2 GLM指摘採用）。"""
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(ac, "get_decision", lambda e: "pending")
        mids = iter(["mid_day0"])
        monkeypatch.setattr(
            ac.discord_api, "send_message", lambda cid, tok, c: next(mids))
        monkeypatch.setattr(ac.discord_api, "add_reaction", lambda cid, mid, tok, e: None)
        (tmp_path / "articles").mkdir()
        art = tmp_path / "articles" / "my-slug.md"
        art.write_text("---\ntitle: T\n---\n\n新しい本文\n", encoding="utf-8")
        entry = entries["106"]
        entry["slug"] = "my-slug"
        entry["content_hash"] = "stale"
        from datetime import datetime, timezone
        entry["last_notify_date"] = datetime.now(timezone.utc).date().isoformat()  # 初回通知日=当日
        monkeypatch.setattr(ac, "REPO_ROOT", str(tmp_path))
        assert ac.handle_entry(entry, issue_num=106, pat="p", webhook_url="") == "renotified"  # 当日でも再通知する

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
        monkeypatch.setattr(ac, "REPO_ROOT", str(tmp_path))
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


class TestGitPushFailLoud:
    def test_push_failure_raises_runtime_error(self, monkeypatch):
        """push失敗は黙殺せずfail-loud（MLR指摘採用・二重転送防止）。"""
        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
            class R:
                stderr = "rejected: protected branch"
                returncode = 1 if len(cmd) > 1 and cmd[1] == "push" else 0

            return R()

        monkeypatch.setattr(ac.subprocess, "run", fake_run)
        try:
            ac.git_commit_push("test")
        except RuntimeError as exc:
            assert "git push失敗" in str(exc)
        else:
            raise AssertionError("RuntimeErrorが投げられなかった")


class TestGitCommitPushOrder:
    def test_order_add_commit_then_pull_rebase_then_push(self, monkeypatch):
        """entries変更（unstaged json）が残ったままpull --rebaseが先行すると必ず失敗する順序回帰テスト。

        2026-11-28実測事故: forwarded時にentries.popでunstaged modifiedが生じ、
        先行したpull --rebaseが「cannot pull with rebase: You have unstaged changes」
        で拒否され状態jsonのpushが失敗（run 46108013219・exit 1実測）。
        discover.yml/publish.ymlは11-27に73beb22で修復済みの同型欠陥の
        approve_checker.py側修復漏れ。add/commitをrebase前に移動して解消。
        """
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
            calls.append((cmd[1], tuple(cmd[2:])))

            class R:
                stdout = ""
                stderr = ""
                returncode = 0
            return R()

        monkeypatch.setattr(ac.subprocess, "run", fake_run)
        ac.git_commit_push("test")

        assert [c[0] for c in calls] == ["config", "config", "add", "commit",
                                         "pull", "push"], calls
        assert calls[0] == ("config", ("user.name", "github-actions[bot]")), calls
        assert calls[1] == ("config",
                            ("user.email",
                             "github-actions[bot]@users.noreply.github.com")), calls
        assert calls[4] == ("pull", ("--rebase",)), calls  # pullは必ず--rebase付き

    def test_commit_identity_error_fails_loud(self, monkeypatch):
        """commit失敗（identity欠如等・nothing to commit以外）はfail-loud。

        2026-11-28実測: runnerにuser設定が無くcommitがexit 128で失敗しても
        capture_outputでstderrが握り潰され静かなearly returnしていた
        （entries push未実行・ジョブログに痕跡なし=silent failure・mktemp隔離
        再現実験でCOMMIT_EXIT=128実測）。
        """
        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
            class R:
                stdout = ""
                stderr = "fatal: empty ident name"
                returncode = 128 if len(cmd) > 1 and cmd[1] == "commit" else 0
            return R()

        monkeypatch.setattr(ac.subprocess, "run", fake_run)
        try:
            ac.git_commit_push("test")
        except RuntimeError as exc:
            assert "git commit失敗" in str(exc)
        else:
            raise AssertionError("RuntimeErrorが投げられなかった")

    def test_commit_nothing_to_commit_is_ok(self, monkeypatch):
        """nothing to commit（変更なし）は正常系・pull/pushは実行しない。"""
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
            op = cmd[1] if len(cmd) > 1 else cmd[0]
            is_commit = len(cmd) > 1 and cmd[1] == "commit"
            calls.append(op)

            class R:
                stdout = "nothing to commit" if is_commit else ""
                stderr = ""
                returncode = 1 if is_commit else 0
            return R()

        monkeypatch.setattr(ac.subprocess, "run", fake_run)
        ac.git_commit_push("test")

        assert calls == ["config", "config", "add", "commit"], calls  # pull/pushは飛ばされる



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
