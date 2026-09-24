"""filter_suiko_warn.py のテスト（Phase 0項目④・v4準拠の2検出器フィルタ）"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "filter_suiko_warn",
    Path(__file__).resolve().parent.parent / "scripts" / "phase0" / "filter_suiko_warn.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["filter_suiko_warn"] = mod
_spec.loader.exec_module(mod)


class TestFilterLines:
    def test_admits_only_v4_categories(self):
        payload = """{"findings": [
            {"category": "redundant_light_verb", "excerpt": "開発を行っ"},
            {"category": "hype_expression", "excerpt": "劇的に向上します"},
            {"category": "forbidden_phrase", "excerpt": "それでは"},
            {"category": "sentence_too_long", "excerpt": "長い文"}
        ]}"""
        lines = mod.filter_lines(payload)
        assert len(lines) == 2
        assert lines[0].startswith("redundant_light_verb:")
        assert lines[1].startswith("hype_expression:")

    def test_broken_json_returns_empty(self):
        assert mod.filter_lines("壊れたJSON{") == []

    def test_no_findings_returns_empty(self):
        assert mod.filter_lines('{"findings": []}') == []
