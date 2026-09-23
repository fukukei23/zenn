"""test_ranker_roundtrip.py — ranker render→parse往復の損失防止テスト（MLR r1修正・2026-09-23）

render_mdが旧行に書く "-" が次回parseで欠落するとランキング111件が消失する
データ損失バグ（Gemini#2 critical）の回帰テスト。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranker import parse_ranking_md  # noqa: E402


class TestReachRoundTrip:
    def test_dash_reach_row_parses(self):
        """render_mdが書く "-"（reach未採点行）が次回parseで欠落しないこと。"""
        md = """| 順位 | スコア | ファイル | 日本語タイトル | バズ | 技術 | 重要 | 状態 | ❤ | 入口 |
|------|--------|----------|---------------|------|------|------|------|---|------|
| 1 | 26 | `old.md` | 旧行 | 8 | 9 | 9 | published | 3 | - |
| 2 | 25 | `new.md` | 新行 | 8 | 9 | 8 | draft | 0 | 5 |
"""
        import tempfile
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md)
            path = f.name
        recs = parse_ranking_md(path)
        os.unlink(path)
        assert len(recs) == 2, f"both rows must parse, got {len(recs)}"
        assert recs[0]["reach"] is None, '"-" should map to None'
        assert recs[1]["reach"] == 5

    def test_old_9col_row_still_parses(self):
        """旧9列フォーマット（入口列なし）の後方互換。"""
        md = """| 順位 | スコア | ファイル | 日本語タイトル | バズ | 技術 | 重要 | 状態 | ❤ |
|------|--------|----------|---------------|------|------|------|------|---|
| 1 | 26 | `old.md` | 旧行 | 8 | 9 | 9 | published | 3 |
"""
        import tempfile
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md)
            path = f.name
        recs = parse_ranking_md(path)
        os.unlink(path)
        assert len(recs) == 1
        assert recs[0]["reach"] is None
