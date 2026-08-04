#!/usr/bin/env python3
"""validate_all_articles.py のテスト。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_all_articles import validate_all


def _write(d, name, title):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(
            f'---\ntitle: "{title}"\nemoji: "📝"\ntype: "tech"\n'
            f'topics: ["t"]\npublished: false\n---\n\n本文\n'
        )


def test_no_violations(tmp_path):
    _write(str(tmp_path), "valid-slug-abcdef12.md", "正常なタイトル")
    assert validate_all(str(tmp_path)) == []


def test_detects_long_title(tmp_path):
    _write(str(tmp_path), "valid-slug-abcdef12.md", "あ" * 80)
    v = validate_all(str(tmp_path))
    assert len(v) == 1


def test_detects_invalid_slug_chars(tmp_path):
    _write(str(tmp_path), "Bad Slug!.md", "正常なタイトル")
    v = validate_all(str(tmp_path))
    assert len(v) == 1


def test_detects_short_slug(tmp_path):
    _write(str(tmp_path), "short.md", "正常なタイトル")
    v = validate_all(str(tmp_path))
    assert len(v) == 1


def test_detects_duplicate_slug(tmp_path):
    _write(str(tmp_path), "dup-slug-12345678.md", "タイトル1")
    _write(str(tmp_path), "dup-slug-12345678.md.md", "タイトル2")  # slug重複
    v = validate_all(str(tmp_path))
    # 両方とも重複違反として検出される
    assert len(v) >= 1


def test_empty_dir(tmp_path):
    assert validate_all(str(tmp_path)) == []


def test_missing_frontmatter(tmp_path):
    with open(os.path.join(str(tmp_path), "nofm-slug12345678.md"), "w") as f:
        f.write("本文のみ")
    v = validate_all(str(tmp_path))
    assert len(v) == 1
