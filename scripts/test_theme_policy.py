"""test_theme_policy.py — 選題型分類と配合強制のテスト（spec §5・2026-09-23）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from theme_policy import classify_topic_type, enforce_theme_ratio  # noqa: E402


class TestClassifyTopicType:
    def test_story_title_is_cross(self):
        assert classify_topic_type(
            "公務員がOpenClawで24時間AI執事を作った3ヶ月の記録",
            "3ヶ月の運用記録と数字") == "cross"

    def test_guide_title_is_cross(self):
        assert classify_topic_type(
            "TDD（テスト駆動開発）を初めて学ぶ人のための完全ガイド",
            "入門向けの全体像解説") == "cross"

    def test_specific_error_title_is_single(self):
        assert classify_topic_type(
            "孤立サロゲートでUnicodeEncodeErrorを防ぐ",
            "ログ保存前の無害化の実装") == "single"

    def test_single_function_topic_is_single(self):
        assert classify_topic_type(
            "pytest importlibモードで同名テスト競合を回避する方法",
            "test_hidden.py 競合の回避策") == "single"

    def test_design_title_is_cross(self):
        assert classify_topic_type(
            "Claude Code commit巻き込み事故を3層hookで防ぐ設計",
            "設計思想と運用のまとめ") == "cross"

    def test_empty_strings_are_single(self):
        # 空文字は判断不能=single側に倒す（誤ってcross量産しない安全側）
        assert classify_topic_type("", "") == "single"


class TestEnforceThemeRatio:
    def test_all_cross_passes(self):
        topics = [
            {"title": "1年で20プロジェクトを作った話", "summary": "体験談"},
            {"title": "設計原則の入門ガイド", "summary": "入門"},
            {"title": "マルチエージェント設計の全体像", "summary": "設計まとめ"},
        ]
        filtered, needs = enforce_theme_ratio(topics)
        assert needs is False
        assert len(filtered) == 3

    def test_all_single_triggers_regenerate(self):
        topics = [
            {"title": "UnicodeEncodeErrorの回避方法", "summary": "無害化"},
            {"title": "exit code 78で衝突回避", "summary": "CLI設計"},
            {"title": "test_hidden.py競合回避", "summary": "importlib"},
        ]
        filtered, needs = enforce_theme_ratio(topics)
        assert needs is True

    def test_two_single_one_cross_needs_regenerate(self):
        topics = [
            {"title": "体験談: 1年の記録", "summary": "まとめ"},
            {"title": "UnicodeEncodeErrorの回避", "summary": "実装"},
            {"title": "bare except全廃の手順", "summary": "実装"},
        ]
        # cross 1/3 < 0.7 → 再生成要求（単発は捨てない・filteredにも残す）
        filtered, needs = enforce_theme_ratio(topics)
        assert needs is True
        assert len(filtered) == 3  # 単発を削除はしない（捨てない設計）

    def test_empty_topics_needs_regenerate(self):
        filtered, needs = enforce_theme_ratio([])
        assert needs is True
        assert filtered == []
