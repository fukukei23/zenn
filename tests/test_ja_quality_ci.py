"""ja_quality_ci.py のテスト（warn-only契約・fail-open）"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ja_quality_ci", Path(__file__).resolve().parent.parent / "scripts" / "ja_quality_ci.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["ja_quality_ci"] = mod
_spec.loader.exec_module(mod)


def run_main(monkeypatch, tmp_path, check_ret, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(mod, "build_lines", lambda: check_ret)
    rc = mod.main()
    out = capsys.readouterr().out
    return rc, out, summary.read_text(encoding="utf-8") if summary.exists() else ""


class TestWarnOnlyContract:
    def test_issues_found_returns_zero(self, monkeypatch, tmp_path, capsys):
        ret, out, _ = run_main(monkeypatch, tmp_path,
                               ["⚠️ **日本語品質の指摘 2件** → 投稿は継続"], capsys)
        assert ret == 0
        assert "指摘 2件" in out

    def test_all_paths_return_zero(self, monkeypatch, tmp_path, capsys):
        """slug失敗・点検不能・OK・例外の全経路でexit 0（blockしない）"""
        for lines in (["⚠️ slug抽出失敗 → スキップ"],
                      ["⚠️ 点検不能 → 投稿は継続"],
                      ["✅ 日本語品質OK（指摘0件）"],
                      ["⚠️ 日本語品質チェック自体が失敗 → 投稿は継続: RuntimeError: x"]):
            ret, _, _ = run_main(monkeypatch, tmp_path, lines, capsys)
            assert ret == 0

    def test_summary_file_written(self, monkeypatch, tmp_path, capsys):
        _, _, summary = run_main(monkeypatch, tmp_path, ["✅ OK"], capsys)
        assert "日本語品質チェック" in summary
