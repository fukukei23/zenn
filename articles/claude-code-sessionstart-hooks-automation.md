---
title: "SessionStartフックでClaude Code CLIを自動構成する実践"
emoji: "⚙️"
type: "tech"
topics: ["claudecode", "cli", "automation", "hooks"]
published: false
---

## はじめに

Claude Code CLIには、セッション開始時に自動実行されるフック（SessionStart hooks）があります。この仕組みを使って、セッション開始時にプロキシ起動・シークレット同期・セキュリティチェック等を自動化できます。

本記事では、11個のSessionStartフックを運用して得た知見と、直面した問題の解決記録を紹介します。

## SessionStartフックとは

Claude Codeの設定ファイル（`~/.claude/settings.json`）に、セッション開始時に実行するコマンドを登録できます。

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "bash /path/to/script.sh"
      }
    ]
  }
}
```

Claude Code起動時に、登録したスクリプトが順次実行されます。stdoutはClaude Codeのコンテキストに送られ、`/dev/tty`または`>&2`でターミナルに表示されます。

## フック構成（11個）

```
~/.claude/scripts/
├ llm/
│   └ start-glm-proxy.sh          # GLM Rate Proxy起動
├ config/
│   └ sync-secrets-to-settings.sh # シークレット同期
├ security/
│   └ check-command-safety.sh     # コマンド安全チェック
├ session/
│   ├── load-handoff.sh           # 前回セッション情報読込
│   ├── load-obsidian-log.sh      # SSOT日記読込
│   ├── startup-banner.sh         # 起動バナー生成
│   ├── generate-handoff.sh       # ハンドオフ情報生成
│   └ save-session-log.sh         # セッションログ保存
├ obsidian/
│   └ check-mcp-guide-diff.sh     # MCP設定差分検知
├ git/
│   └ check-submodules.sh         # サブモジュール状態確認
└ app/
    └ update-indexes.sh           # インデックス更新
```

各フックの役割を説明します。

### 1. GLM Rate Proxy起動（start-glm-proxy.sh）

LLMルーティングの中核となるローカルプロキシを起動します。

処理内容:
1. 既に起動中か確認（`pgrep` + health check）
2. 起動中なら`settings.json`の`ANTHROPIC_BASE_URL`を検証
3. 未起動ならプロキシをバックグラウンド起動
4. 起動失敗時はZ.AI直接URLにフォールバック

```bash
ensure_settings_url() {
    if [ -f "$SETTINGS" ]; then
        sed -i "s|\"ANTHROPIC_BASE_URL\": \"[^\"]*\"|\"ANTHROPIC_BASE_URL\": \"$1\"|" "$SETTINGS"
    fi
}
```

重要なのは、**プロキシがhealthyな場合でもURL検証を実行すること**です。PC移行等で`settings.json`が初期化されると、プロキシが動いていてもClaude Codeが直接Z.AIに接続してしまう問題がありました。

### 2. シークレット同期（sync-secrets-to-settings.sh）

`~/.secrets.env`から環境変数を読み込み、`settings.json`の`env`セクションに同期します。APIキーをファイルに直書きせず、環境変数経由で注入する仕組みです。

### 3. ハンドオフ読込（load-handoff.sh）

前回セッション終了時に生成した`handoff.md`を読み込み、Claude Codeのコンテキストに送ります。

```bash
if [[ -f "$HANDOFF_FILE" ]]; then
  echo "--- Handoff ---"
  cat "$HANDOFF_FILE"
  echo "--- /Handoff ---"
fi
```

これにより、新セッションのClaude Codeが前回の作業内容を引き継げます。

### 4. 起動バナー（startup-banner.sh）

各フックのステータスを集約し、1つのバナーとしてターミナルに表示します。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 🚀 Claude Code セッション開始
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ✅ Secrets: 6/6 loaded
 ✅ GLM Proxy: healthy
 ✅ Security: active
 ✅ MCP Guide: synced
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 📋 前回: NexusCoreリファクタリング完了
 📝 本日3セッション | 最終: README整理 (12:27終了)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 直面した問題と解決

### 問題1: バナーが表示されない

**症状**: 新しいターミナルで`claude`を起動した際、起動バナーが表示されないことがあった。

**原因**: SessionStartフック内のシェルは**非対話シェル**で実行されるため、`/dev/tty`や`>&2`への出力がターミナルに届かない場合があります。ターミナルの状態や起動方式によって`/dev/tty`の接続可否が変わるため、「出る時と出ない時」がありました。

**解決**: バナー出力を`.bashrc`の`claude()`シェル関数（対話シェル）側に移動しました。SessionStartフックはステータスファイル（`/tmp/claude-startup/*.status`）に結果を書き出すだけにし、`.bashrc`側でそのファイルを読み取って表示します。

```
フック: ステータスファイル書き出し（確実）
  ↓
.bashrc claude(): ステータスファイル読取→バナー表示（確実）
```

### 問題2: プロキシが動いていてもフォールバックが効かない

**症状**: PC移行後、GLM→MiniMaxフォールバックが機能していなかった。

**原因**: プロキシが既に稼働中の場合、health check OKで即`exit 0`しており、`settings.json`の`ANTHROPIC_BASE_URL`を検証していませんでした。PC移行で設定が初期化され、プロキシをバイパスするURLになっていました。

**解決**: 全3パス（healthy / 起動成功 / 起動失敗）で`ensure_settings_url()`を呼び出すようにしました。

```bash
# healthy でもURL検証を実行
if pgrep -f "python3 -m glm_rate_proxy" > /dev/null 2>&1; then
    if curl -sf -m 2 http://127.0.0.1:8787/proxy/status > /dev/null 2>&1; then
        ensure_settings_url "$PROXY_URL"   # ← 追加
        exit 0
    fi
fi
```

### 問題3: シークレット同期によるMCP設定の再生成

**症状**: MCPサーバーを削除しても、次のセッション開始時に復元される。

**原因**: `sync-secrets-to-settings.sh`が環境変数を`settings.json`に同期する際、存在しないMCPサーバーのエントリを`null`値で再生成していました。

**解決**: スクリプトから不要なMCPサーバーのjqエントリを削除しました。

## フック設計の原則

### 1. 各フックは独立させる

フック間に依存関係を作らないことが重要です。1つのフックが失敗しても、他のフックが動くようにします。

### 2. ステータスをファイルで伝達する

フックの実行結果は`/tmp/claude-startup/`配下のステータスファイルに書き出します。他のフックや`.bashrc`側から参照しやすくなります。

### 3. stdoutと/dev/ttyを使い分ける

- **stdout（デフォルト）**: Claude Codeのコンテキストに送られる。Claudeが読む情報
- **`/dev/tty`**: ターミナルに直接表示。ユーザーが見る情報
- **`>&2`（stderr）**: Claude Codeプロセスに吸収されるが、`/dev/tty`が使えない場合のフォールバック

### 4. フェイルセーフを組み込む

プロキシ起動失敗時はZ.AI直接URLにフォールバックする等、フックが失敗してもClaude Code自体は使える状態を保ちます。

## PC移行時のチェックリスト

新しいPC環境でClaude Codeをセットアップする際、最低限確認すべき項目です。

1. `~/.secrets.env`にAPIキーが設定されているか
2. `settings.json`に`ANTHROPIC_BASE_URL`エントリが存在するか
3. `start-glm-proxy.sh`を一度手動実行して動作確認
4. `grep "ANTHROPIC_BASE_URL" ~/.claude/settings.json` → プロキシURLであること
5. `curl -s http://127.0.0.1:8787/proxy/status` → 正常応答

## この構成の限界

- **WSL2限定**: `/dev/tty`の挙動が環境依存のため、他環境では調整が必要
- **フック数の増加**: 11個のフックが順次実行されるため、起動に数秒かかる
- **設定ファイルの2箇所管理**: `~/.claude.json`と`~/.claude/settings.json`の両方を意識する必要がある

## おわりに

SessionStartフックは、Claude Code CLIを自分の開発フローに適合させる強力な仕組みです。プロキシ起動、シークレット管理、セッション引き継ぎ等を自動化することで、セッション開始時の手動作業をゼロにできます。

ただし、非対話シェルでの実行という制約があるため、ユーザーに見せる情報は`.bashrc`側に出す等の工夫が必要です。フック設計では「独立性」「フェイルセーフ」「stdout/tty使い分け」の3点を意識すると、安定した構成になります。

### 関連記事

- [Claude CodeのMCPツールがコンテキストを圧迫する問題の調査と最適化記録](https://zenn.dev/fukukei23/articles/claude-code-mcp-context-optimization)
- [Claude Code CLIをGLM（Z.AI）で代替した話（コスト大幅削減の実測）](https://zenn.dev/fukukei23/articles/claude-code-cost-optimization)
- [月間27億トークンを処理したLLMルーティングの実運用レポート](https://zenn.dev/fukukei23/articles/llm-routing-one-month-report)
