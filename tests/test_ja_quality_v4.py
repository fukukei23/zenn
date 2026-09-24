"""ja_quality.py v4準拠更新のテスト（Phase 0項目②③反映・2026-09-24）

- CHECK_MAX_TOKENS=24000（P95が16000で打ち切られた実測の反映・M3上限262144を確認済み）
- build_promptに「意味が成立しない文」観点を追加（ふくけい採点#3の協議注記=文全体の意味破綻を最上位に）
- 12k字超過時に警告を返す（実測で実用上限12k字と確定・16k字は3連続length切れ）
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("ja_quality", SCRIPTS / "ja_quality.py")
ja_quality = importlib.util.module_from_spec(_spec)
sys.modules["ja_quality"] = ja_quality
_spec.loader.exec_module(ja_quality)


class TestCheckMaxTokens:
    def test_max_tokens_raised_to_24000(self):
        assert ja_quality.CHECK_MAX_TOKENS == 24000


class TestBuildPrompt:
    def test_has_meaning_breakdown_viewpoint(self):
        prompt = ja_quality.build_prompt("t", "本文")
        assert "意味が成立しない文" in prompt

    def test_viewpoint_listed_first(self):
        """意味破綻を最上位観点として明示（#3協議注記の反映）"""
        prompt = ja_quality.build_prompt("t", "本文")
        idx_meaning = prompt.find("意味が成立しない文")
        idx_subject = prompt.find("主語のすり替え")
        assert 0 < idx_meaning < idx_subject


class TestLengthWarning:
    def test_short_body_no_warning(self):
        assert ja_quality.length_warning("短い本文") is None

    def test_over_12k_chars_warns(self):
        body = "あ" * 12001
        warn = ja_quality.length_warning(body)
        assert warn is not None
        assert "12000" in warn

    def test_exactly_12k_no_warning(self):
        assert ja_quality.length_warning("あ" * 12000) is None
