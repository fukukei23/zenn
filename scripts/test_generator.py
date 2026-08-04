#!/usr/bin/env python3
"""generator.py のユニットテスト（slug生成・バリデーション）。"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import slug_from_title, validate_article, SLUG_MIN, SLUG_MAX


class TestSlugFromTitle:
    def test_ascii_with_hash_suffix(self):
        slug = slug_from_title("Fail Closed Design")
        assert slug.startswith("fail-closed-design-")
        assert SLUG_MIN <= len(slug) <= SLUG_MAX

    def test_japanese_only_fallback(self):
        slug = slug_from_title("はじめてのPython入門")
        assert SLUG_MIN <= len(slug) <= SLUG_MAX
        assert re.match(r"^[a-z0-9_-]+$", slug)

    def test_similar_titles_produce_unique_slugs(self):
        s1 = slug_from_title("Python Guide for Beginners A")
        s2 = slug_from_title("Python Guide for Beginners B")
        assert s1 != s2

    def test_long_title_truncated_within_limit(self):
        slug = slug_from_title("A" * 200)
        assert len(slug) <= SLUG_MAX

    def test_only_valid_chars(self):
        slug = slug_from_title("Test Title Here!")
        assert re.match(r"^[a-z0-9_-]+$", slug), f"invalid chars in: {slug}"

    def test_deterministic(self):
        # 同一タイトルは同一slug（再現性）
        assert slug_from_title("Same Title") == slug_from_title("Same Title")


class TestValidateArticle:
    def test_valid_article_no_errors(self):
        assert validate_article("正常なタイトル", "valid-slug-abc12345", []) == []

    def test_title_too_long_71(self):
        errs = validate_article("あ" * 71, "valid-slug-abc12345", [])
        assert any("title" in e.lower() or "70" in e for e in errs)

    def test_title_boundary_70_ok(self):
        assert validate_article("あ" * 70, "valid-slug-abc12345", []) == []

    def test_slug_too_short(self):
        errs = validate_article("正常", "short", [])
        assert any("slug" in e.lower() for e in errs)

    def test_slug_too_long_51(self):
        errs = validate_article("正常", "a" * 51, [])
        assert errs

    def test_slug_invalid_chars(self):
        errs = validate_article("正常", "Invalid Slug!", [])
        assert any("文字種" in e or "slug" in e.lower() for e in errs)

    def test_slug_duplicate(self):
        errs = validate_article("正常", "dup-slug-12345678", ["dup-slug-12345678"])
        assert any("重複" in e or "duplicate" in e.lower() for e in errs)

    def test_multiple_errors_returned(self):
        errs = validate_article("あ" * 80, "Bad Slug!", ["Bad Slug!"])
        assert len(errs) >= 2
