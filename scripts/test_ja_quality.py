"""test_ja_quality.py — 日本語品質gateのテスト（2026-09-23・ふくけい承認A案）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ja_quality import build_prompt, check_file, extract_json_block, parse_issues  # noqa: E402

BROKEN = "「自分は大丈夫」と思って読んでいただけると思っています。"
FIXED = "「自分は大丈夫」と思っている人にこそ、読んでほしい内容です。"


class FakeClient:
    """generator.chat互換のモック（choices[0].message.contentを返す）。"""

    def __init__(self, content):
        self._content = content

    class _Msg:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = FakeClient._Msg(c)

    class _Resp:
        def __init__(self, c):
            self.choices = [FakeClient._Choice(c)]

    def chat(self, *args, **kwargs):  # 互換のためgenerator.chat(client,...)形式
        pass

    class completions:  # noqa: N801
        pass


def _client_returning(content):
    """OpenAI SDK互換のclient.chat.completions.createモックを作る。"""

    class Msg:
        def __init__(self, c):
            self.content = c

    class Choice:
        def __init__(self, c):
            self.message = Msg(c)

    class Resp:
        def __init__(self, c):
            self.choices = [Choice(c)]

    class Completions:
        def create(self, **kwargs):
            return Resp(content)

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client()


class TestBuildPrompt:
    def test_prompt_contains_title_and_body(self):
        p = build_prompt("テストタイトル", "# はじめに\n" + BROKEN)
        assert "テストタイトル" in p
        assert BROKEN in p
        assert "JSON" in p

    def test_prompt_mentions_broken_sentence_types(self):
        p = build_prompt("t", "本文")
        assert "主語" in p or "破綻" in p


class TestParseIssues:
    def test_parse_valid_json(self):
        text = '{"issues": [{"quote": "壊れ文", "problem": "主語すり替え", "suggestion": "修正案"}]}'
        issues = parse_issues(text)
        assert len(issues) == 1
        assert issues[0]["problem"] == "主語すり替え"

    def test_parse_with_think_block(self):
        text = "<think>思考...</think>" + '{"issues": []}'
        assert parse_issues(text) == []

    def test_parse_garbage_returns_none(self):
        assert parse_issues("説明文だけでJSONなし") is None


class TestExtractJsonBlock:
    def test_extract_object(self):
        assert extract_json_block('前文 {"issues": []} 後文') == '{"issues": []}'


class TestCheckFile:
    def _write(self, tmpdir, body):
        p = os.path.join(tmpdir, "t.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f'---\ntitle: "T"\n---\n\n{body}\n')
        return p

    def test_pass_on_clean_article(self, tmp_path):
        p = self._write(str(tmp_path), FIXED)
        client = _client_returning('{"issues": []}')
        issues = check_file(client, p)
        assert issues == []

    def test_fail_on_broken_sentence(self, tmp_path):
        p = self._write(str(tmp_path), BROKEN)
        client = _client_returning(
            '{"issues": [{"quote": "思って読んでいただける", "problem": "主語すり替え", "suggestion": "読んでほしい"}]}'
        )
        issues = check_file(client, p)
        assert len(issues) == 1

    def test_three_garbage_retries_return_none(self, tmp_path):
        p = self._write(str(tmp_path), "本文")
        client = _client_returning("毎回壊れた応答")
        assert check_file(client, p) is None  # None=点検不能（fail-safe・合格扱いにしない）

    def test_think_stripped_before_parse(self, tmp_path):
        p = self._write(str(tmp_path), BROKEN)
        client = _client_returning(
            '<think>推理</think>{"issues": [{"quote": "q", "problem": "p", "suggestion": "s"}]}'
        )
        issues = check_file(client, p)
        assert len(issues) == 1
