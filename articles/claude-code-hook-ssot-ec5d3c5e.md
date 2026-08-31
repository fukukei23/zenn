---
title: 「Claude Code」呼称ルール警告hook実装：SSOT衛生管理を「ユーザー」→「ふくけい」置換で実現
emoji: 🪝
type: tech
topics:
  - ClaudeCode
  - Python
  - hook
  - SSOT
published: false
---

# はじめに

Claude Codeの設定（CLAUDE.md・スキル・hook）を1つのリポジトリでSSOT（Single Source of Truth＝単一の情報源）として管理していると、地味に困るのが「呼称の揺れ」です。人間を指す語が文書ごとに「ユーザー」だったり一人称だったりブレると、そのルールを読むClaude Code自身まで主語が揺れ始め、応答の一貫性が崩れます。

本記事では、この揺れを「spec承認 → 呼称ルール新設 → 警告hook実装 → 既存文書43箇所の機械置換」という流れで解決した実装を、自分の設定リポジトリでの経験をもとに解説します。

# 1. まずspecを書く──「人間を指す文脈」だけを置換する

いきなりhookを書き始めるのではなく、まず仕様メモ（spec）を1枚書いて自分で承認してから手を付けました。内容は次の3点です。

- 人間は「ふくけい」、Claude Codeは「CC」と呼称を固定
- エージェント側の一人称は禁止（主語は行動主体で書く）
- 置換対象は「**人間を指す文脈の**『ユーザー』」のみ

最後の1行が重要です。「ユーザー名」や「ユーザーエージェント」のような技術用語まで置換すると文意が壊れるためです。機械置換とhook検知の両方に同じ例外を効かせるために、先に「何を置換し、何を残すか」を文書化しておくと、後工程の実装がブレません。承認済みのspecを参照する形で、ルール集の最上位層（層1）に呼称ルールを新設しました。

# 2. ブロックなし警告hookの実装

Claude Codeのhookは、ファイル編集などのイベント発生時にstdinへJSONを受け取る仕組みです。PostToolUseでWrite/Edit/MultiEditを補足し、書き込み内容に「ユーザー（助詞つき含む）」があれば警告します。

いちばん大きな設計判断は「**ブロックしない**」こと。hookをブロックモードにすると、誤検知のたびに編集作業が止まります。呼称の揺れは致命傷にならないので、警告だけ出して人間とClaude Code側で判断する方針にしました。判断基準はシンプルで、「誤検知で止めるコスト＞放置のコストなら警告のみ」です。

```python
#!/usr/bin/env python3
"""呼称ルール警告hook: 人間を指す『ユーザー』を検知して警告する(ブロックなし)"""
import json
import re
import sys

TARGET_TOOLS = {"Write", "Edit", "MultiEdit"}
# 技術用語との衝突を避ける除外ワード
EXCLUDES = ("ユーザー名", "ユーザーエージェント")
# 助詞つきも拾う(「ユーザーは」「ユーザーの」...)
PATTERN = re.compile(r"ユーザー[はもがのを]?")

def collect_texts(tool_name: str, tool_input: dict) -> list[str]:
    """ツール種別ごとに、書き込み対象のテキストを収集する"""
    if tool_name == "Write":
        return [tool_input.get("content", "")]
    if tool_name == "Edit":
        return [tool_input.get("new_string", "")]
    return [e.get("new_string", "") for e in tool_input.get("edits", [])]

def main() -> None:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    if tool_name not in TARGET