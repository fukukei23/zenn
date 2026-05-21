---
title: "Claude CodeのMCPツールがコンテキストを圧迫する問題の調査と最適化記録"
emoji: "🔧"
type: "tech"
topics: ["claudecode", "mcp", "ai"]
published: false
---

## はじめに

Claude Code CLIでは、MCP（Model Context Protocol）サーバーが提供するツール定義が会話コンテキストを消費します。ツール数が増えると、実際の会話に使えるコンテキストが減っていきます。

本記事では、MCPツール定義がコンテキストの**11〜28%を占有**していた問題を調査し、最適化した記録を紹介します。

## 問題の発見

`/context`コマンドで現在のコンテキスト使用状況を確認したところ、MCP toolsだけで21.4kトークン（10.7%）を消費していました。

```
Context Usage
├ System prompt: 5.7k (2.8%)
├ System tools: 17.6k (8.8%)
├ MCP tools: 21.4k (10.7%)  ← これ
├ Custom agents: 2.9k (1.4%)
├ Memory files: 2.5k (1.2%)
├ Skills: 2.4k (1.2%)
└ Messages: 26.7k (13.4%)
```

21.4kならまだ許容範囲ですが、最悪のケースでは**223.8k（112%）**に達し、会話を開始できない状態になることも確認しました（後述）。

## MCPツールのコンテキスト消費の仕組み

Claude Codeは、セッション開始時に登録済みMCPサーバーからツール一覧を取得し、その定義をコンテキストにロードします。ツール定義には、ツール名・説明・パラメータスキーマが含まれます。

例えば、GitHub MCPサーバーは約50のツールを提供します。

```
├ mcp__plugin_github_github__search_code: 266 tokens
├ mcp__plugin_github_github__pull_request_read: 565 tokens
├ mcp__plugin_github_github__issue_write: 442 tokens
├ ...（計50ツール）
```

1ツールあたり100〜600トークン。サーバーごとに数千〜数万トークンを消費します。

## 調査：コンテキスト圧迫の原因特定

### 原因1: 設定ファイルが2箇所に存在

Claude CodeのMCP設定は**2つのファイル**に分散していました。

| ファイル | 役割 |
|---|---|
| `~/.claude.json` | グローバル設定 |
| `~/.claude/settings.json` | プロジェクト設定 |

両方がマージされてロードされるため、`settings.json`だけで編集しても`.claude.json`側にエントリが残っていれば、削除が反映されません。

### 原因2: SessionStartフックによる再生成

Claude CodeのSessionStartフックで実行されるスクリプト（`sync-secrets-to-settings.sh`）が、環境変数を`settings.json`に同期する際、**存在しないMCPサーバーのエントリをnull値で再生成**していました。

セッション開始のたびに、削除したはずのサーバーが復元される状態でした。

### 原因3: デスクトップアプリの自動ロード（Windows）

Windows版デスクトップアプリ（Claude Code Desktop v2.1.142）では、ユーザー設定とは別に**24個のMCPサーバーが自動ロード**されていました。

| 項目 | WSL CLI（正常） | デスクトップアプリ |
|---|---|---|
| MCPサーバー数 | 7（ユーザー設定通り） | 24（自動ロード） |
| MCP tools消費 | 21.9k (11%) | 223.8k (112%) |
| ツール数 | 85 | 354 |

Postman、Sentry、Gmail、Figma、Slack等の主要SaaS連携が、ユーザーの明示的な設定なしにロードされていました。

6回の異なる設定変更（MCP server削除、profiles無効化、plugin cache削除、marketplaces削除、plugin無効化、Extensions削除）を試みましたが、**223.8kは一切変動しませんでした**。

## 最適化の実施（WSL CLI側）

### Step 1: 設定ファイル2箇所の統合確認

`claude mcp remove` CLIコマンドを使用して、両ファイルから確実に削除。

```bash
claude mcp remove linear
claude mcp remove sentry
claude mcp remove supabase
claude mcp remove tavily
claude mcp remove stripe
```

### Step 2: SessionStartフックの修正

`sync-secrets-to-settings.sh`から、5サーバーのjqエントリを削除。これでセッション開始時の再生成を防止。

### Step 3: 結果

| 項目 | 最適化前 | 最適化後 |
|---|---|---|
| MCPサーバー数 | 9 | **6** |
| MCP tools消費 | 56.7k (28%) | **21.4k (11%)** |

約35kトークンの削減。削除した5サーバー（linear、sentry、stripe、supabase、tavily）は、当時のプロジェクトで使用していなかったため、影響なし。

## デスクトップアプリ側の対策

デスクトップアプリ側は、CLI側のような設定変更では解決しませんでした。以下の対策を講じました。

### Desktop Extensionsの削除

`C:\Users\<user>\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\Claude Extensions`にあった7個の拡張機能（grafana:71ツール、pdf-filler:37ツール等）のうち、6個を削除。

- 223.8k → 213.2k（10.6k削減）

### コネクタの切断

Desktopアプリの「Connectors」セクションから、使用していない17個のコネクタ（Postman、Sentry、Gmail等）を切断。維持したのは5個（GitHub、Context7、Exa、glm、minimax）。

しかし、切断後も168.7kのまま。74個のシステム組み込みツール（Claude_in_Chrome、computer-use等）は削除不可でした。

### 現在の状況

- **WSL CLI**: 21.4k/200k（正常、メイン使用）
- **デスクトップアプリ**: 168.7k/200k（Anthropicサポート調査中）

Anthropicサポートに問い合わせたところ、「7〜8倍の差は異常に高い。エンジニアリングチームの調査が必要」との回答。人間担当者にエスカレーション済みです。

## MCPツールの必要性評価基準

最適化の際、各MCPサーバーの必要性を以下の基準で評価しました。

| 基準 | 内容 |
|---|---|
| 使用頻度 | 過去1ヶ月で実際に使ったか |
| プロジェクト関連 | 現在のプロジェクトで必要か |
| 代替手段 | 他のツール（Web検索等）で代替可能か |
| トークン消費 | 何ツール・何トークン消費しているか |

評価結果の例：

| MCPサーバー | ツール数 | トークン | 判定 |
|---|---|---|---|
| brave-search | 6 | ~5.5k | **維持**（高頻度使用） |
| github | 50 | ~14k | **維持**（PR/Issue管理） |
| context7 | 2 | ~1.2k | **維持**（ドキュメント検索） |
| playwright | 25 | ~5k | **維持**（UI自動化） |
| linear | 30 | ~8k | **削除**（不使用） |
| sentry | 24 | ~6k | **削除**（不使用） |

## MCPコンテキスト最適化のチェックリスト

同じ問題に遭遇した方向けに、チェックリストをまとめます。

1. **`/context`で現状確認**: MCP toolsの消費トークンを把握
2. **使用していないサーバーを特定**: `claude mcp list`で一覧確認
3. **`claude mcp remove`で削除**: 手動編集ではなくCLIコマンドを使用（2ファイル確実削除）
4. **SessionStartフックの確認**: スクリプトがMCP設定を上書きしていないか
5. **Desktop Extensionsの確認**: Windows版ではExtensionsが別管理
6. **コネクタの確認**: Desktop版のConnectorsセクションで不要なものを切断
7. **最適化後に`/context`で再確認**: 削減効果を検証

## おわりに

MCPツールは強力ですが、その便利さゆえにコンテキストを圧迫しやすくなります。「入れているだけで安心」ではなく、定期的な見直しが重要です。

特に、プロジェクトの変更や技術スタックの移行後は、不要なMCPサーバーが残存しがちです。`/context`コマンドを定期的に確認する習慣をつけることをおすすめします。

### 関連記事

- [Claude Code CLIをGLM（Z.AI）で代替した話（コスト大幅削減の実測）](https://zenn.dev/fukukei23/articles/claude-code-cost-optimization)
- [Claude Code CLIにMiniMaxをフォールバックとして組み込んだ話](https://zenn.dev/fukukei23/articles/claude-code-minimax-fallback)
- [月間27億トークンを処理したLLMルーティングの実運用レポート](https://zenn.dev/fukukei23/articles/llm-routing-one-month-report)
