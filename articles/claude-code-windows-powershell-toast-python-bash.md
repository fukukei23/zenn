---
title: "【Claude Code】Windows通知をPowerShell Toastで実装：Python・bash連携の具体例"
emoji: "📝"
type: "tech"
topics: ["Claude Code", "PowerShell", "Windows", "bash"]
published: false
---

title: "【Claude Code】Windows通知をPowerShell Toastで実装：Python・bash連携の具体例"
emoji: "📩"
type: "tech"
topics: ["Claude Code", "PowerShell", "Windows", "bash"]
published: false
---

## はじめに

Claude CodeなどのAIエージェントを長時間動かしていると、「エージェントが作業を完了したタイミング」や「ユーザーの承認が必要なタイミング」を知りたくなります。

私は普段、Windows PC上でWSL（Linux環境）を使いながら開発を行っており、AIエージェントの設定ファイルやスクリプト群は自分のリポジトリで一元管理しています。今回は、この環境において**「WSL/Linux環境からWindows側の通知（Toast通知）を呼び出す」**という連携を実装したので、その具体的な方法を解説します。

PowerShell、Python、bashを連携させる少し変わった構成になりますが、クロスプラットフォームな環境を構築している方の参考になれば嬉しいです。

## なぜPowerShellのToast通知を使うのか？

Windows環境における通知方法はいくつかありますが、今回はPowerShellを経由した「Toast通知」を採用しました。

Toast通知とは、Windows画面の右下に表示されるポップアップのことです。これを利用することで、裏側で動いているスクリプトからの通知を、ユーザーが見逃さずに済みます。また、Windowsに標準搭載されている機能を利用するため、サードパーティ製の追加アプリをインストールする必要がありません。

しかし、スクリプトの大部分はWSL（Linux側）のbashやPythonで動いています。そのため、**「Linux側の処理から、Windows側の通知機能をどう叩くか」**が今回の課題となりました。

## 環境に依存しないパス設計の工夫

連携スクリプトを作る上で最も意識したのが、「新しくPCを買い替えたり、別の環境にリポジトリをクローンしたりした際に、すぐに動くようにする」という点です。

過去の自分の実装では、スクリプト内に `~/username/scripts/...` のような実ユーザー名を含むパス（ハードコード）が残っており、環境移行時にエラーになることがありました。これを解決するために、環境変数を活用した設計に見直しています。

### Pythonでのパス解決の具体例

設定ファイルに記載されたパス（例: `~/.claude/logs`）を読み込む際、Pythonでは `pathlib` の `expanduser()` を使うことで、実行環境のユーザーディレクトリに合わせて安全にパスを展開できます。

```python
import subprocess
from pathlib import Path

def send_windows_notification(message: str):
    # ホームディレクトリからの相対パスを環境に依存せず解決
    script_path = Path("~/.scripts/notify.ps1").expanduser()
    
    # WSL側からWindowsのPowerShellを呼び出すコマンドを構築
    command = [
        "powershell.exe",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script_path),
        "-Message", message
    ]
    
    try:
        # サブプロセスとしてPowerShellを実行
        subprocess.run(command, check=True)
        print("通知を送信しました")
    except subprocess.CalledProcessError as e:
        print(f"通知の送信に失敗しました: {e}")

# エージェントが承認を求めた際の通知を実行
send_windows_notification("Claude Code: 実行承認をお待ちしています")
```

このように `Path().expanduser()` を噛ませることで、スクリプトをそのままコピーするだけで、どんなユーザー名の環境でも動作するようになります。

## bash・PowerShellとの連携実装

Pythonだけでなく、bashスクリプトから直接通知を飛ばしたいケースもあります。bashの場合は `$HOME` 環境変数を利用し、WSL側のパスをWindows側のパスとして解釈させる工夫が必要です。

### bashラッパースクリプトの例

WSLからWindowsの実行ファイルを呼び出す際は、`wslpath` コマンドを使うとパスの変換がスムーズです。

```bash
#!/bin/bash

# 通知メッセージを引数から受け取る（デフォルトメッセージ付き）
MESSAGE=${1:-"タスクが完了しました"}

# $HOME を使って環境非依存でスクリプトの場所を特定
SCRIPT_PATH="$HOME/.scripts/notify.ps1"

# WSLのパスをWindows側のパスに変換
WIN_SCRIPT_PATH=$(wslpath -w "$SCRIPT_PATH")

# PowerShellを呼び出してToast通知を表示
powershell.exe -ExecutionPolicy Bypass -File "$WIN_SCRIPT_PATH" -Message "$MESSAGE" > /dev/null 2>&1
```

### PowerShell（notify.ps1）の実装

呼び出されるPowerShell側は、引数を受け取ってWindowsの標準機能で通知を表示します。エラーログなどを適切なディレクトリ（`$env:USERPROFILE` 配下など）に出力するようにしておくと、トラブルシューティングが容易になります。

```powershell
param(
    [string]$Message = "デフォルトの通知メッセージです"
)

# WindowsのAPIを使ってToast通知を表示
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)

# タイトルとメッセージを設定
$template.GetElementsByTagName("text").Item(0).AppendChild($template.CreateTextNode("Claude Code")) | Out-Null
$template.GetElementsByTagName("text").Item(1).AppendChild($template.CreateTextNode($Message)) | Out-Null

$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Claude Code App").Show($toast)
```

## おわりに

今回は、Claude CodeのようなAIエージェントの実行環境に、Windowsの通知機能を追加する取り組みについて紹介しました。

**「PowerShellで通知を出す」「Pythonやbashからそれを呼び出す」「環境変数を使ってハードコードを排除する」** という3つの工夫を組み合わせることで、強力で移植性の高い自動化パイプラインが構築できます。

WSLとWindowsを行き来する開発環境は複雑に見えますが、責任を適切に分割すればメンテナンスしやすい仕組みを作ることができます。AIエージェントを長時間走らせ、バックグラウンドで作業を任せる際の参考にしてみてください。