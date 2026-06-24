---
title: "Claude Code Desktop版でMCPを使ってコストを抑える方法"
emoji: "💸"
type: "tech"
topics: ["claudecode", "mcp", "glm", "コスト最適化", "claude"]
published: true
---

## 結論

Claude CodeのDesktop版（Windowsアプリ）は、MCPサーバーにGLMやMiniMaxを登録するだけで、定型作業・大量処理を安いLLMに委譲してコストを抑えられます。

本体はSonnetのままなので品質を保ちつつ、単純な作業だけを外注する形です。

## なぜMCPを使うのか

Desktop版のアプリ（特にMicrosoft Store版）は、CLI版と違って環境変数を書き換えられません。つまりエンドポイントを丸ごとGLMに差し替えるという方法が使えない。

そこでMCPを使って、Sonnetの外側に安いLLMへの「出口」を作ります。

## 設定手順

### 1. MCPサーバーを用意する

公式APIを直接叩く自作サーバーをPythonで書きました。JSON-RPC 2.0のstdioサーバーをurllibのみで実装しています（SDK不要）。

tools/call が来たら ~/.secrets.env からAPIキーを読んでGLM/MiniMaxのエンドポイントに投げるだけ。100から200行程度で動きます。

### 2. 設定ファイルに登録する

重要: Windows Desktop版（Microsoft Store版）はサンドボックス化（MSIX）のため、設定ファイルの場所が通常とは異なります。

正しいパス:
C:\Users\ユーザー名\AppData\Local\Packages\Claudeのパッケージフォルダ\LocalCache\Roaming\Claude\claude_desktop_config.json

~/.claude/settings.json や AppData\Roaming\Claude\ も存在しますが、どちらも実際には読まれていないコピーです。上記のパッケージキャッシュ内のファイルが本物です。

正しいファイルを開いて、MCPサーバーを追加します。

{
  "mcpServers": {
    "glm": {
      "command": "python3",
      "args": ["/path/to/glm-mcp-server.py"]
    },
    "minimax": {
      "command": "python3",
      "args": ["/path/to/minimax-mcp-server.py"]
    }
  }
}

### 3. 動作確認

Claude Code Desktop上で /mcp と入力すると、登録したサーバーの接続状態が確認できます。connected になっていればOKです。

あとはClaude（Sonnet）が会話の流れから判断して委譲してくれます。もしくはプロンプトに「GLMを使って」と明示的に指示することもできます。

## どんな作業を委譲するか

コスト削減の効果が大きい用途の目安です。

委譲に向いている作業の例:
- ドキュメント・コメント生成（大量のテキスト処理で課金が嵩む）
- データの整形・変換（定型的でSonnetの高精度が不要）
- コードの雛形生成（繰り返しの多い作業）
- 翻訳・要約（GLMでも十分な品質が出る）

複雑な設計判断・デバッグ・コードレビューはSonnetのまま任せる、というメリハリが基本方針です。

## まとめ

- Desktop版はCLIと違ってエンドポイントを差し替えられないが、MCPで安いLLMへの「委譲口」を作れる
- 設定ファイルはパッケージキャッシュ内の場所を使う（ここを間違えると繋がらない）
- 本体をSonnetに保ちながら、単純な作業だけをコスト削減できる

---

関連記事: CLI版とDesktop版でGLM/MiniMaxの役割がまるで違う話（./claude-code-desktop-mcp-cost-delegation）

---

この記事はClaude Code（GLM-5.1）と一緒に書きました。
