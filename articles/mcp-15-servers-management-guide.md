---
title: "Claude Codeで15個MCPサーバーを管理する方法（選定・運用・トラブル対応）"
emoji: "🔧"
type: "tech"
topics: ["claudecode", "mcp", "ai", "devtools"]
published: false
---

## はじめに

Claude CodeのMCP（Model Context Protocol）を使うと、GitHub操作、Web検索、ブラウザ自動化などがClaude Code内から直接実行できます。

私は現在 **15個のMCPサーバー** を運用していますが、ここに至るまでに多くの試行錯誤がありました。

本記事では、MCPサーバーの**選定基準・設定方法・運用のコツ・トラブル対応**を実践的に解説します。

## MCPサーバーとは（前提知識）

MCPは、Claude Codeから外部ツールを呼び出すためのプロトコル:

```
Claude Code
  ↓ ツール呼び出し
MCPサーバー（ローカルプロセス）
  ↓ API呼び出し
外部サービス（GitHub, Brave, Stripe...）
  ↓ 結果返却
Claude Code（コンテキストに追加）
```

設定は `settings.json` に書くだけ:

```json
{
    "mcpServers": {
        "server-name": {
            "command": "npx",
            "args": ["-y", "@package/server"],
            "env": { "API_KEY": "..." }
        }
    }
}
```

## 15個の選定基準

### カテゴリ別の必要性

#### 開発必須（常時有効）

| MCP | 用途 | 選定理由 |
|-----|------|---------|
| **GitHub** | PR/Issue/ファイル操作 | `gh` CLIより自然言語で操作可能 |
| **Brave Search** | Web検索 | リアルタイム情報の取得に不可欠 |
| **Context7** | ライブラリドキュメント検索 | 最新ドキュメントの参照。Web検索より精度が高い |
| **Playwright** | ブラウザ自動操作 | UI確認・スクレイピング・テストに必須 |

#### コミュニケーション

| MCP | 用途 | 選定理由 |
|-----|------|---------|
| **Discord** | メッセージ送受信 | チーム内連携・通知の自動化 |
| **tweetly** | X（Twitter）投稿 | Zenn記事のSNS発信 |

#### ユーティリティ

| MCP | 用途 | 選定理由 |
|-----|------|---------|
| **Mermaid** | 図表生成 | アーキテクチャ図・フローチャート |
| **Web Reader** | URL読み込み | 記事・ドキュメントの全文取得 |
| **4_5v MCP** | 画像分析 | スクリーンショットの分析 |

### 選定の判断フロー

```
新しいツールが必要になった
  ↓
内蔵ツール（Bash/Read/WebSearch）で代用可能？
  ↓ No
npmパッケージとしてMCPサーバーが存在する？
  ↓ Yes
使用頻度が週1以上見込める？
  ↓ Yes
→ settings.jsonに追加
```

## 設定のベストプラクティス

### APIキーの管理

**❌ 悪い例**: settings.jsonに直書き
```json
{
    "env": { "API_KEY": "sk-abc123..." }
}
```

**✅ 良い例**: 環境変数から読み込み
```bash
# ~/.secrets.env
BRAVE_API_KEY=xxx
GITHUB_TOKEN=xxx

# SessionStart hook で注入
source ~/.secrets.env
```

settings.json側:
```json
{
    "env": { "API_KEY": "${BRAVE_API_KEY}" }
}
```

### 設定の同期

```
~/.claude/settings.json          ← 実行環境
  ↔（手動同期）
obsidian-ssot/01_DECISIONS/claude-code/設定ファイル/  ← 履歴管理
```

設定変更時は **必ず両方を更新**。変更理由をコミットメッセージに残す。

## トラブル対応

### 1. MCPサーバーが起動しない

```bash
# 原因調査
npx @package/server  # 直接起動してエラーを確認

# よくある原因:
# - Node.js バージョン不一致
# - APIキー未設定
# - ポート競合
```

### 2. コンテキスト不足エラー

MCPが多すぎてコンテキストが圧迫される場合:

```json
// 一時的にMCPを無効化
{
    "mcpServers": {
        "heavy-server": {
            "disabled": true  // ← 追加
        }
    }
}
```

### 3. ツール定義の肥大化

一部のMCPは50+のツールを定義しており、コンテキストを大量消費:

```bash
# 各MCPのツール数を確認
claude mcp list
```

ツール数が多いMCPは**使用頻度と天秤にかけて**削除を検討。

## MCPツール使い分けガイド

| やりたいこと | 使うツール | 理由 |
|-------------|-----------|------|
| PR作成 | MCP GitHub | 自然言語でPR作成可能 |
| Web検索 | MCP Brave Search | 実行速度が速い |
| ドキュメント検索 | MCP Context7 | ライブラリ固有の最新情報 |
| ブラウザ操作 | MCP Playwright | スクショ・フォーム入力 |
| ファイル読み書き | 内蔵Read/Write | MCP不要 |
| シェルコマンド | 内蔵Bash | MCP不要 |

## MCP使用頻度の分析結果

```
月間使用回数（2026年5月・1ヶ月間）:

GitHub         ████████████████████ 200+
Brave Search   ████████████████ 150+
Context7       ████████ 80+
Playwright     ███ 30+
Discord        ██ 20+
Mermaid        █ 10+
Web Reader     █ 5+
4_5v MCP       ▏ 3+
tweetly        ▏ 2+
```

上位3つ（GitHub/Brave/Context7）で **使用量の85%** を占めています。

## まとめ

1. **選定**: 使用頻度とコンテキスト消費のバランスで判断
2. **設定**: APIキーは環境変数で管理、設定ファイルはGit管理
3. **運用**: 定期的に使用頻度を分析して断捨離
4. **トラブル**: 直接起動でエラー確認、不要なMCPは無効化

MCPは強力なツールですが、**「入れているだけ」では逆効果**。定期的なメンテナンスが大切です。

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
