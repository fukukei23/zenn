# Zenn Contents

> This repository manages technical articles for Zenn, a Japanese publishing platform for engineers. Pushing to the `master` branch triggers automatic deployment, making articles live at [zenn.dev/fukukei23](https://zenn.dev/fukukei23).

## プロジェクト概要

Zennと連携し、技術記事の管理と自動公開を行うリポジトリです。ローカルでMarkdown形式の記事を作成し、`master` ブランチにプッシュすることでZenn上に自動公開されます。執筆ワークフローの一元管理とSSOTの実現を目的としています。

## 技術スタック

- Markdown（Zenn記法）
- Git / GitHub
- Zenn CI/CD（masterブランチpushによる自動連携）

## プロジェクト構造

```text
zenn/
└── articles/
    ├── ai-agent-vps-security.md
    ├── ai-coding-governance-collapse.md
    ├── ai-governance-stit-irg.md
    ├── caddy-nginx-replacement-vps.md
    ├── claude-code-cost-optimization.md
    ├── claude-code-minimax-fallback.md
    ├── claude-code-obsidian-ssot.md
    └── pw-stealth-enhanced-python-anti-detection.md
```

## セットアップ

特別な依存関係はありません。テキストエディタとGit環境のみ必要です。

```bash
git clone <repository-url>
cd zenn
```

## 使い方

### 記事の作成

1. `articles/` ディレクトリに `<slug名>.md` を作成する
2. ファイルの先頭にZennフロントマターを記述する

```yaml
---
title: "記事タイトル"
emoji: "😎"
type: "tech" # "tech" or "idea"
topics: ["tag1", "tag2"]
published: true  # falseで下書き
---
```

3. 記事本文をMarkdownで記述する
4. `master` ブランチにコミット&プッシュするとZennが自動検知して公開する

### 既存記事一覧

| slug | タイトル |
|------|----------|
| `claude-code-cost-optimization` | Claude Code CLI コスト最適化 |
| `claude-code-minimax-fallback` | Claude Code MiniMax フォールバック |
| `claude-code-obsidian-ssot` | Claude Code Obsidian SSOT |
| `ai-agent-vps-security` | AIエージェント VPS セキュリティ |
| `ai-coding-governance-collapse` | AIコーディング ガバナンス崩壊 |
| `ai-governance-stit-irg` | AIガバナンス STIT-IRG |
| `caddy-nginx-replacement-vps` | Caddy Nginx置き換え VPS |
| `pw-stealth-enhanced-python-anti-detection` | Playwright ステルス Python 検出回避 |

## 管理情報

- Zennアカウント: https://zenn.dev/fukukei23
- SSOT管理: `01_DECISIONS/claude-code/zenn-publishing-workflow.md`（Obsidian SSOT内）
