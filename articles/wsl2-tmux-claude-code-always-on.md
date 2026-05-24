---
title: "WSL2 + tmuxでClaude Code CLIを常時稼働させる環境構築"
emoji: "🖥️"
type: "tech"
topics: ["wsl2", "tmux", "claudecode", "linux"]
published: false
---

## はじめに

Claude CodeはCLI版が最も柔軟に使えます。しかし、Windows環境でCLIを常時稼働させるには工夫が必要です。

私は **WSL2 + tmux** で5〜10セッションを同時稼働させています。本記事では、この環境構築の完全ガイドを解説します。

## 環境構成

```
Windows 11
  └── WSL2 (Ubuntu 24.04)
       └── tmux（ターミナルマルチプレクサ）
            ├── Claude Code セッション1（プロジェクトA）
            ├── Claude Code セッション2（プロジェクトB）
            └── Claude Code セッション3（プロジェクトC）
```

## Step 1: WSL2のセットアップ

### インストール

```powershell
# PowerShell（管理者）
wsl --install -d Ubuntu-24.04
```

### 初期設定

```bash
# パッケージ更新
sudo apt update && sudo apt upgrade -y

# 必須ツール
sudo apt install -y tmux git curl jq

# Node.js（Claude Code用）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Claude Code
npm install -g @anthropic-ai/claude-code
```

### WSL2のメモリ設定

```ini
# C:\Users\<username>\.wslconfig
[wsl2]
memory=16GB
swap=8GB
```

## Step 2: tmuxの設定

### 基本設定（~/.tmux.conf）

```tmux
# プレフィックスキー変更（Ctrl+a）
unbind C-b
set -g prefix C-a
bind C-a send-prefix

# ペイン分割
bind | split-window -h
bind - split-window -v

# マウス有効化
set -g mouse on

# 256色対応
set -g default-terminal "screen-256color"

# ステータスバー
set -g status-bg black
set -g status-fg white
set -g status-right '#{session_name} | %H:%M'
```

### Claude Code用セッション管理スクリプト

```bash
#!/bin/bash
# ~/scripts/claude-session.sh

SESSION_NAME=${1:-main}
PROJECT_DIR=${2:-$HOME}

tmux has-session -t $SESSION_NAME 2>/dev/null

if [ $? != 0 ]; then
    tmux new-session -d -s $SESSION_NAME -c $PROJECT_DIR
    tmux send-keys -t $SESSION_NAME "claude" Enter
    echo "Created session: $SESSION_NAME"
else
    echo "Session exists: $SESSION_NAME"
fi

tmux attach -t $SESSION_NAME
```

使い方:
```bash
# プロジェクトごとにセッション作成
claude-session nexuscore ~/projects/NexusCore
claude-session atelier ~/projects/atelier-kyo-manager
claude-session ssot ~/projects/obsidian-ssot
```

## Step 3: Androidからのリモート操作

### Termux（Android）の設定

```bash
# Termux で SSH接続
ssh your_username@$(hostname -I | awk '{print $1}')

# tmuxセッションにアタッチ
tmux attach -t nexuscore

# デタッチ（セッションは維持）
# Ctrl+a → d
```

**メリット**: 外出先からスマホでClaude Codeを操作可能。セッションは常時稼働。

## Step 4: SessionStart hooksの活用

Claude Code起動時に自動実行されるフックを設定:

```json
// ~/.claude/settings.json
{
    "hooks": {
        "SessionStart": [
            {
                "type": "command",
                "command": "~/.claude/scripts/session/load-obsidian-log.sh"
            }
        ]
    }
}
```

このフックで:
1. 今日・昨日のSSOT日記を自動読み込み
2. バックログ（未完了タスク）を自動表示
3. ターミナルにサマリー表示

## Step 5: Claude Code起動の最適化

### .bashrc のカスタマイズ

```bash
# Claude Code起動関数
claude() {
    # プロキシ生存確認
    if curl -s http://localhost:8787/proxy/status > /dev/null 2>&1; then
        export ANTHROPIC_BASE_URL="http://127.0.0.1:8787"
    fi

    # Claude Code起動
    command claude "$@"
}
```

### プロジェクトごとの設定

各プロジェクトに `CLAUDE.md` を配置:

```
project/
  CLAUDE.md     ← プロジェクト固有ルール
  .claude/
    settings.local.json  ← ローカル設定
```

## 運用のTips

### 複数セッションの管理

```bash
# セッション一覧
tmux list-sessions

# セッション間の移動
# Ctrl+a → s（セッション一覧表示）

# 特定セッションにアタッチ
tmux attach -t session_name
```

### ログの確認

```bash
# Claude Codeのログ
ls ~/.claude/logs/

# プロキシのログ
tail -f /tmp/glm-proxy.log
```

### リソース監視

```bash
# メモリ使用量
free -h

# Node.jsプロセス（Claude Code）
ps aux | grep node

# ディスク使用量
df -h
```

## トラブルシューティング

### WSL2が重い

```ini
# .wslconfig でメモリ制限
[wsl2]
memory=8GB
```

### tmuxセッションが消える

WSL2の再起動で消える可能性あり。重要なセッションは **自動復旧スクリプト** を cron に登録:

```bash
# crontab -e
@reboot ~/scripts/restore-tmux-sessions.sh
```

### Claude Codeが応答しない

```bash
# プロセス確認
ps aux | grep claude

# 強制終了
pkill -f claude

# 再起動
tmux send-keys -t session_name "claude" Enter
```

## まとめ

| 要件 | 解決策 |
|------|--------|
| 常時稼働 | WSL2 + tmux |
| 複数プロジェクト | tmuxセッション分割 |
| 外出先からの操作 | SSH + Termux |
| 環境の自動復元 | SessionStart hooks |
| コスト管理 | LLMルーティングプロキシ |

この環境で、私は毎日5〜10のClaude Codeセッションを同時稼働させています。

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
