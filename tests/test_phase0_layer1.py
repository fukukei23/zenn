"""phase0_layer1.py のテスト（日本語品質3層統合 Phase 0・項目①測定基盤）"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "phase0"))

from phase0_layer1 import extract_samples, preprocess_markdown


class TestExtractSamples:
    def test_count_and_unique(self, tmp_path):
        for i in range(50):
            (tmp_path / f"doc_{i:03d}.md").write_text(f"本文{i}", encoding="utf-8")
        got = extract_samples("zenn", str(tmp_path), 15)
        assert len(got) == 15
        assert len({s["path"] for s in got}) == 15

    def test_deterministic(self, tmp_path):
        for i in range(50):
            (tmp_path / f"doc_{i:03d}.md").write_text(f"本文{i}", encoding="utf-8")
        a = extract_samples("zenn", str(tmp_path), 15)
        b = extract_samples("zenn", str(tmp_path), 15)
        assert [s["path"] for s in a] == [s["path"] for s in b]

    def test_spread(self, tmp_path):
        """等間隔抽出で冒頭集中しない（cherry-picking防止の機械担保）"""
        for i in range(50):
            (tmp_path / f"doc_{i:03d}.md").write_text(f"本文{i}", encoding="utf-8")
        got = extract_samples("zenn", str(tmp_path), 15)
        nums = sorted(int(os.path.basename(s["path"])[4:7]) for s in got)
        assert nums[0] < 10
        assert nums[-1] >= 40

    def test_short_pool_returns_all(self, tmp_path):
        for i in range(3):
            (tmp_path / f"doc_{i}.md").write_text("x", encoding="utf-8")
        got = extract_samples("shainai", str(tmp_path), 15)
        assert len(got) == 3


class TestPreprocess:
    def test_strips_frontmatter(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text(
            "---\ntitle: テスト\n---\n\nこれは本文です。\n",
            encoding="utf-8",
        )
        title, body = preprocess_markdown(str(f))
        assert title == "テスト"
        assert "title:" not in body
        assert "これは本文です。" in body

    def test_strips_code_blocks(self, tmp_path):
        f = tmp_path / "b.md"
        f.write_text(
            "説明文A\n\n```python\nprint('ここは対象外')\n```\n\n説明文B\n",
            encoding="utf-8",
        )
        _, body = preprocess_markdown(str(f))
        assert "説明文A" in body
        assert "説明文B" in body
        assert "print(" not in body

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "c.md"
        f.write_text("本文のみ。\n", encoding="utf-8")
        title, body = preprocess_markdown(str(f))
        assert title == ""
        assert body == "本文のみ。\n"
