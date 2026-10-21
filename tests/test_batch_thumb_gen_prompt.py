import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import batch_thumb_gen as bg


def test_load_article_returns_title_and_head(tmp_path):
    a = tmp_path / "articles" / "sample.md"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text(
        '---\ntitle: "BDD入門"\nemoji: "🎭"\ntype: "tech"\n---\n\n## はじめに\n\n'
        + ("本文テスト用。" * 50) + "\n",
        encoding="utf-8",
    )
    title, head = bg.load_article_title_and_head(str(a), head_chars=200)
    assert title == "BDD入門"
    assert "本文テスト用" in head
    assert len(head) <= 200


def test_load_article_no_frontmatter_returns_empty_title():
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("frontmatterなし本文\n" * 30)
        path = f.name
    title, head = bg.load_article_title_and_head(path, head_chars=50)
    assert title == ""
    assert "frontmatterなし" in head
    assert len(head) <= 50


def test_build_image_prompt_combines_style_prefix():
    prompt = bg.build_image_prompt(
        theme_en="three-layer quality assurance for AI-generated code",
        keywords_en="pipeline stages, shield icon, checklist",
    )
    assert prompt.startswith("minimal flat illustration")
    assert "three-layer quality assurance" in prompt
    assert "pipeline stages" in prompt


def test_build_image_prompt_excludes_japanese_characters():
    """日本語が prompt に混入すると画像内に文字化けするため混入しないこと。"""
    prompt = bg.build_image_prompt(theme_en="code review", keywords_en="magnifier, bug")
    assert not any("一" <= ch <= "鿿" for ch in prompt)


def test_build_thumb_copy_truncates_title_to_15_chars():
    # title[:15] が呼ばれる想定（句読点なし・スペース終端）
    assert bg.build_thumb_copy("Claude Code CLIにMiniMaxをフォールバックとして組み込んだ話（安いLLMを7層で守り抜く戦略）") \
        == "Claude Code CLI"


def test_build_thumb_copy_uses_separator_when_present():
    # 句読点「、」があればそこで切る
    assert bg.build_thumb_copy("nginx書けない人、Caddy最強設定") == "nginx書けない人"


def test_build_thumb_copy_strips_leading_decoration():
    assert bg.build_thumb_copy("【NexusCore Stage 2】品質保証") == "NexusCore Stage 2"


def test_build_thumb_copy_handles_short_title():
    assert bg.build_thumb_copy("短い") == "短い"


def test_load_article_handles_unquoted_title():
    """Zenn デフォルトの引用符なし title 形式に対応する。"""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("---\ntitle: 引用符なしタイトル\nemoji: 🎭\n---\n\n本文\n")
        path = f.name
    title, _ = bg.load_article_title_and_head(path, head_chars=50)
    assert title == "引用符なしタイトル"
