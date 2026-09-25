"""ja_quality_fix.py のテスト（公開ゲート: 検知→修正→報告→再承認）"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ja_quality_fix", Path(__file__).resolve().parent.parent / "scripts" / "ja_quality_fix.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["ja_quality_fix"] = mod
_spec.loader.exec_module(mod)


class TestApplyFixes:
    def test_applies_exact_match(self):
        text = "前文です。このフィルタリングを行うことで楽になります。後文です。"
        fixes = [{"original": "このフィルタリングを行うことで楽になります。",
                  "revised": "このフィルタで楽になります。",
                  "problem": "冗長"}]
        new_text, skipped = mod.apply_fixes(text, fixes)
        assert "このフィルタで楽になります" in new_text
        assert skipped == []

    def test_skip_when_original_not_found(self):
        text = "本文には無い文です。"
        fixes = [{"original": "本文に無い文", "revised": "x", "problem": "p"}]
        _, skipped = mod.apply_fixes(text, fixes)
        assert len(skipped) == 1


class TestBuildComment:
    def test_contains_before_after_and_instruction(self):
        comment = mod.build_comment(
            [{"original": "元の文A", "revised": "直した文B", "problem": "冗長"}],
            [{"original": "見つからない文", "revised": "x", "problem": "p"}])
        assert "元の文A" in comment and "直した文B" in comment
        assert "/approve" in comment  # 再承認依頼が含まれる
        assert "自動修正できなかった" in comment  # スキップ分の報告

    def test_empty_fixes(self):
        assert "適用可能な修正なし" in mod.build_comment([], [])


class TestGateDecision:
    def test_clean_when_no_issues(self, monkeypatch, tmp_path):
        (tmp_path / "dummy-slug.md").write_text("問題のない本文です。", encoding="utf-8")
        import types
        ja_quality_mod = types.ModuleType("ja_quality")
        ja_quality_mod.check_file = lambda client, path: []
        sys.modules["ja_quality"] = ja_quality_mod
        try:
            gate, comment = mod.run_gate("dummy-slug", object(),
                                         articles_dir=str(tmp_path))
        finally:
            sys.modules.pop("ja_quality", None)
        assert gate == "clean"
        assert comment == ""

    def test_fixed_when_issues_found(self, monkeypatch, tmp_path):
        article = tmp_path / "dummy-slug.md"
        article.write_text("このフィルタリングを行うことで楽になります。", encoding="utf-8")
        import types
        ja_quality_mod = types.ModuleType("ja_quality")
        ja_quality_mod.check_file = lambda client, path: [
            {"quote": "このフィルタリングを行うことで楽になります。",
             "problem": "冗長", "suggestion": "このフィルタで楽になります。"}]
        sys.modules["ja_quality"] = ja_quality_mod
        commits = []
        monkeypatch.setattr(mod, "commit_and_push",
                            lambda slug: commits.append(slug))
        monkeypatch.setattr(mod, "revise_sentence",
                            lambda client, o, p, s: "このフィルタで楽になります。")
        try:
            gate, comment = mod.run_gate("dummy-slug", object(),
                                         articles_dir=str(tmp_path))
        finally:
            sys.modules.pop("ja_quality", None)
        assert gate == "fixed"
        assert "このフィルタで楽になります" in comment  # 修正後が報告に含まれる
        assert "/approve" in comment  # 再承認依頼
        assert commits == ["dummy-slug"]  # 修正をコミット済み
