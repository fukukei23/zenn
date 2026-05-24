---
title: "15個MCPサーバーを運用して分かった不要なものと必要なもの"
emoji: "🔌"
type: "tech"
topics: ["claudecode", "mcp", "ai", "tools"]
published: false
---

## はじめに

Claude Codeの **MCP（Model Context Protocol）サーバー**。外部ツールをClaude Codeから直接使える強力な仕組みですが、**入れすぎると逆効果**になります。

私は一時期 **15個のMCPサーバー** を同時稼働していました。そしてクラッシュしました。

本記事では、15個のMCPサーバーを運用して分かった「本当に必要なもの」と「断捨離すべきもの」の基準を解説します。

## MCPサーバーとは

MCPは、Claude Codeから外部ツール（Web検索、GitHub、Playwright等）を直接呼び出すプロトコルです:

```json
// settings.json
{
    "mcpServers": {
        "github": { "command": "npx", "args": ["@anthropic/github-mcp"] },
        "brave-search": { "command": "npx", "args": ["@anthropic/brave-search-mcp"] }
    }
}
```

**問題**: MCPサーバーが増えると **コンテキストウィンドウを消費** します。

## インシデント: 15個MCPでクラッシュ

### 発生時の状況

```
settings.json: 15個のMCPサーバー
コンテキスト使用率: 常に90%以上
症状: Claude Codeの応答が遅延・不正確に
```

### 原因分析

各MCPサーバーは起動時に **ツール定義（JSON Schema）** をClaude Codeに送信:

```json
{
    "name": "brave_web_search",
    "description": "...",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": { "type": "string" },
            "count": { "type": "number" },
            // ... 多いと50行以上
        }
    }
}
```

15個のMCPサーバー × 平均5ツール = **75個のツール定義** がコンテキストを圧迫。

### 実際の影響

| MCP数 | コンテキスト消費 | 体感品質 |
|--------|----------------|---------|
| 5個 | 15% | 良好 |
| 10個 | 30% | やや重い |
| **15個** | **45%** | **クラッシュ** |

## 断捨離基準

### 基準1: 使用頻度

**1ヶ月間の使用回数** を計測:

| MCPサーバー | 月間使用回数 | 判定 |
|-------------|------------|------|
| GitHub | 200+ | ✅ 必須 |
| Brave Search | 150+ | ✅ 必須 |
| Context7（ドキュメント検索） | 80+ | ✅ 必須 |
| Playwright（ブラウザ） | 30+ | ✅ 保持 |
| Discord | 20+ | ✅ 保持 |
| Mermaid（図表） | 10+ | ⚠️ 検討 |
| Web Reader | 5+ | ⚠️ 検討 |
| 4_5v MCP（画像分析） | 3+ | ❌ 削除 |
| tweetly（X投稿） | 2+ | ❌ 削除 |

### 基準2: コンテキスト消費量

ツール定義の大きさを確認:

```bash
# settings.json から各MCPのツール数を数える
grep -c '"name"' ~/.claude/settings.json
```

ツール数が多いMCPは**必要時のみ有効化**するのが正解。

### 基準3: 代替手段の有無

| MCP | 代替手段 | 判定 |
|-----|---------|------|
| Brave Search | WebSearchツール（内蔵） | ⚠️ 重複検討 |
| Mermaid | テキストベース図表 | ❌ 削除可能 |
| GitHub | `gh` CLIコマンド | ⚠️ 併用 |

## 最適化後の構成（10個）

```
必須（常時有効）:
  ├── GitHub        — PR/Issue/ファイル操作
  ├── Brave Search  — Web検索
  ├── Context7      — ライブラリドキュメント検索
  ├── Playwright    — ブラウザ自動操作
  └── Discord       — メッセージ送受信

有用（常時有効）:
  ├── Web Reader    — URL読み込み
  └── 4_5v MCP      — 画像分析

軽量（常時有効）:
  └── Mermaid       — 図表生成

実験的（必要時有効）:
  └── tweetly       — X投稿
```

## MCP管理のベストプラクティス

### 1. 定期的な使用頻度分析

```bash
# セッションログからMCP使用状況を集計
grep "mcp__" ~/.claude/logs/*.json | \
  jq '.tool_name' | sort | uniq -c | sort -rn
```

### 2. 設定ファイルのバージョン管理

```bash
# settings.json の変更をGit管理
cd ~/.claude
git add settings.json
git commit -m "MCP断捨離: 15→10個に削減"
```

### 3. MCPガイドの維持

`MCPツール使い分けガイド.md` を作成し、各MCPの用途・使用頻度・代替手段を記録。Claude Code起動時に自動チェックで差分を検知。

## 教訓

1. **MCPは多いほど良いわけではない** — コンテキストを圧迫する
2. **使用頻度を計測してから判断** — 感覚ではなく数字で
3. **代替手段を確認** — CLIコマンドで済むならMCPは不要
4. **設定をGit管理** — 変更履歴で rollback 可能に

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
