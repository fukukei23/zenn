---
title: 【Claude Code】夜間ループCLI統合設計：night_loop.pyで学ぶTDD 11テスト実装術
emoji: 🌙
type: tech
topics:
  - ClaudeCode
  - Python
  - TDD
  - CLI
  - 初心者向け
published: false
---

## はじめに

Claude Codeを夜間にcronで自動実行する運用をしていますが、処理が増えるにつれ「スクリプトが乱立して状態管理が破綻する」問題に直面しました。そこで自分のClaude Code設定用リポジトリに、夜間の定期処理を1本にまとめた統合CLI `night_loop.py` を実装しました。

この記事ではその設計思想を、次の4つのキーワードに沿って初心者向けに解説します。

- **案α**：1本の統合CLIにするという設計判断
- **seen I/O + atomic write + .bak復旧**：「処理済み」記録を壊さない仕組み
- **stage1保持**：動いている処理を書き換えずに移行する方法
- **TDD