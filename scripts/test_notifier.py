#!/usr/bin/env python3
"""notifier.py のユニットテスト（ファイル読込ヘルパー）。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from notifier import load_generator_error, load_validation_errors


class TestLoadGeneratorError:
    def test_reads_json(self, tmp_path):
        path = os.path.join(str(tmp_path), "generator_error.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"type": "RuntimeError", "message": "x", "traceback": "tb"}, f
            )
        err = load_generator_error(base_dir=str(tmp_path))
        assert err is not None
        assert err["type"] == "RuntimeError"
        assert err["message"] == "x"

    def test_returns_none_when_missing(self, tmp_path):
        assert load_generator_error(base_dir=str(tmp_path)) is None


class TestLoadValidationErrors:
    def test_reads_json(self, tmp_path):
        path = os.path.join(str(tmp_path), "validation_errors.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"errors": [{"title": "t"}]}, f)
        verrs = load_validation_errors(base_dir=str(tmp_path))
        assert verrs is not None
        assert len(verrs["errors"]) == 1

    def test_returns_none_when_missing(self, tmp_path):
        assert load_validation_errors(base_dir=str(tmp_path)) is None
