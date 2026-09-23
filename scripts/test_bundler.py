"""test_bundler.py — 群化ジェネレータのテスト（spec §4-4・2026-09-23）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundler import bundle_proposals, extract_theme, group_by_theme  # noqa: E402


def _art(fname, title, tags):
    return {"file": fname, "title": title, "tags": tags}


class TestExtractTheme:
    def test_pytest_theme(self):
        assert extract_theme("pytest importlib競合回避", ["pytest", "python"]) == "pytest"

    def test_claude_code_theme(self):
        assert extract_theme("Claude Code hook設計", ["claude-code"]) == "claude-code"

    def test_fallback_to_first_tag(self):
        assert extract_theme("謎のタイトル", ["mystery-tag"]) == "mystery-tag"

    def test_empty_returns_unknown(self):
        assert extract_theme("", []) == "unknown"


class TestGroupByTheme:
    def test_groups_same_theme(self):
        arts = [
            _art("a.md", "pytest A", ["pytest"]),
            _art("b.md", "pytest B", ["pytest"]),
            _art("c.md", "Claude Code hook", ["claude-code"]),
        ]
        groups = group_by_theme(arts)
        assert len(groups["pytest"]) == 2
        assert len(groups["claude-code"]) == 1

    def test_empty_articles(self):
        assert group_by_theme([]) == {}


class TestBundleProposals:
    def test_min_size_filters_small_groups(self):
        arts = [
            _art("a.md", "pytest 1", ["pytest"]),
            _art("b.md", "pytest 2", ["pytest"]),
            _art("c.md", "pytest 3", ["pytest"]),
            _art("d.md", "misc 1", ["misc"]),
        ]
        proposals = bundle_proposals(group_by_theme(arts), min_size=3)
        assert len(proposals) == 1
        assert proposals[0]["theme"] == "pytest"
        assert len(proposals[0]["chapters"]) == 3

    def test_proposal_has_title_and_chapters(self):
        arts = [
            _art("a.md", "pytest 1", ["pytest"]),
            _art("b.md", "pytest 2", ["pytest"]),
            _art("c.md", "pytest 3", ["pytest"]),
        ]
        p = bundle_proposals(group_by_theme(arts))[0]
        assert "pytest" in p["title"]
        assert all("chapter" in c for c in p["chapters"]) or all(
            isinstance(c, dict) for c in p["chapters"])
