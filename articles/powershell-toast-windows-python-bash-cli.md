---
title: "【初心者向け】PowerShell ToastでWindows通知を実装：Python・bash連携でCLIツールの体験を上げる具体例"
emoji: "📝"
type: "tech"
topics: ["PowerShell", "Windows", "CLI", "通知", "初心者向け"]
published: false
---

title: "【初心者向け】PowerShell ToastでWindows通知を実装：Python・bash連携でCLIツールの体験を上げる具体例"
emoji: "🔔"
type: "tech"
topics: ["PowerShell", "Windows", "CLI", "通知", "初心者向け"]
published: false

## はじめに

皆さんは、ターミナル（CLI）で時間のかかるスクリプトやビルド処理を実行しているとき、どうやって完了を知っていますか？
「ターミナルを開きっぱなしにして、ずっと画面を見つめている」「たまに`Alt+Tab`でウィンドウを切り替えて確認する」という方も多いのではないでしょうか。

CLIツールは軽量で便利ですが、長時間の処理（AIモデルの実行、データのバッチ処理、ファイルのダウンロードなど）が終わったことを能動的に教えてくれないことが多いです。しかし、Windowsの標準機能である「Toast通知（画面右下に出るポップアップ）」を活用すれば、処理完了時にデスクトップ上で直感的に完了を知ることができます。

今回は、私が実際に開発・運用しているCLIツール用設定リポジトリ（`claude-config`）で実装した、PythonやbashスクリプトからWindowsの通知を呼び出す仕組みを題材にします。初心者の方でもすぐに真似できるよう、具体的なコード例とともに解説します。

## PowerShell Toast APIの基礎

Windowsでネイティブな通知（Toast）を出す一番手軽な方法は、PowerShellを使うことです。Windows 10以降に標準搭載されているAPIを呼び出すことで、リッチな見た目の通知を簡単に実装できます。

以下は、引数でタイトルとメッセージを受け取って通知を表示するPowerShellスクリプト（`notify.ps1`）の基本形です。

```powershell
# notify.ps1
param(
    [string]$Title = "処理完了",
    [string]$Message = "CLIツールのタスクが終了しました。"
)

# WindowsのToast通知を呼び出すためのアセンブリを読み込む
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null

# アプリケーションID（任意の文字列でOK）
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

# Toast通知のXMLテンプレートを作成
$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>$Title</text>
            <text>$Message</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)

# 通知を作成して表示
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
```

このスクリプトをPowerShell上で実行すると、画面右下にきれいな通知ポップアップが表示されます。これだけであれば非常にシンプルですが、実際の開発現場では「bashスクリプトやPythonスクリプトからこのPowerShellを呼び出したい」というケースがほとんどです。

## bash・PythonからPowerShellを呼び出す実践

WSL（Windows Subsystem for Linux）環境や、Git Bashなどを普段遣いしている場合、メインの処理はbashやPythonで書くことが多いです。ここでは、それらの言語から先ほどの`notify.ps1`を呼び出す方法を解説します。

### ハードコードを避け、環境変数を活用する（実務の知見）

実際の開発現場や自分のツールセットを整備している際、よく陥る罠が「パスのハードコード」です。
つい`/home/user_name/scripts/notify.ps1`のように直書きしてしまうと、新しいPCへ移行した時や、チームメンバーに共有した際にパスの違いでスクリプトが動かなくなってしまいます。

実際に私のリポジトリでも、**「すべてのスクリプト・設定ファイルから特定のユーザー名（`~/`）のハードコードを除去し、環境変数（`$HOME`など）に置き換える」** という修正を行いました。これにより、新しいPCに移行してもスクリプトをそのままコピーするだけで動くようになります。

この前提を踏まえ、環境に依存しない形で通知スクリプトを呼び出してみましょう。

### bashスクリプトからの呼び出し

bashスクリプトからWindowsのPowerShellを呼び出すには、`powershell.exe`（または`pwsh.exe`）を経由します。スクリプトのパスは`$HOME`などの環境変数を使って解決します。

```bash
#!/bin/bash
# notify.sh

# 環境変数HOMEを使ってスクリプトの絶対パスを解決（ハードコード回避）
SCRIPT_DIR="$HOME/path/to/scripts"
PS_SCRIPT="$SCRIPT_DIR/notify.ps1"

# 処理が完了したタイミングで通知を呼び出す
# (ここでは例として単純にsleepで擬似的な処理を表現)
echo "長時間の処理を開始します..."
sleep 5

# PowerShellスクリプトを実行
powershell.exe -ExecutionPolicy Bypass -File "$PS_SCRIPT" \
  -Title "バッチ処理完了" \
  -Message "すべてのデータの同期が終わりました。"
```

`-ExecutionPolicy Bypass`をつけることで、ローカルのスクリプト実行制限を回避しつつ安全に実行できます。

### Pythonからの呼び出し

Pythonから呼び出す場合も基本的な考え方は同じです。`subprocess`モジュールを使用して`powershell.exe`をキックします。パスの操作には標準ライブラリの`pathlib`を使うと、OS間の差異を吸収しやすくなります。

```python
import subprocess
from pathlib import Path
import os

def send_windows_notification(title: str, message: str):
    """WindowsのToast通知をPowerShell経由で送信する"""
    # 実行環境のHOMEディレクトリを取得し、スクリプトへのパスを動的構築
    home_dir = Path(os.environ.get("HOME", os.path.expanduser("~")))
    script_path = home_dir / "path" / "to" / "scripts" / "notify.ps1"

    if not script_path.exists():
        print(f"スクリプトが見つかりません: {script_path}")
        return

    try:
        # powershell.exeを呼び出して実行
        subprocess.run(
            [
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-File", str(script_path),
                "-Title", title,
                "-Message", message
            ],
            check=True,
            capture_output=True
        )
        print("通知を送信しました。")
    except subprocess.CalledProcessError as e:
        print(f"通知の送信に失敗しました: {e.stderr.decode('utf-8', errors='ignore')}")

# 実行例
if __name__ == "__main__":
    # 何か重い処理をした体で...
    send_windows_notification(
        title="AIタスク完了",
        message="ファイルの解析と出力が完了しました。"
    )
```

このようにラッパー関数を作っておくと、CLIツールの最後に `send_windows_notification()` を呼び出すだけで、いつでもWindowsの通知を鳴らせるようになります。

## CLIツールのUX（ユーザー体験）を上げるために

通知を実装したことで、以下のような劇的な改善があります。

1. **バックグラウンド作業への移行**: 画面を見張る必要がなくなるため、待ち時間を別のタスクに充てることができます。
2. **承認やエラーの見逃し防止**: 自動化スクリプトで「ユーザーの承認が必要な場面」や「エラーで止まった場面」になったとき、通知を出すようにすれば、リアルタイムに気づくことができます。

私が運用しているツールでも、定期的に実行されるバッチ処理や、AIによる長時間のファイル生成タスクの完了時にこのスクリプトを組み込んでいます。エラーが起きた際には「処理に失敗しました」と通知されるだけで、作業効率が劇的に向上しました。

## おわりに

今回は、Windows環境でPythonやbashからPowerShell Toast通知を呼び出す方法を解説しました。

「ターミナルの文字出力だけ」から「OSのネイティブ通知」を組み合わせるだけで、ツールの使い勝手はぐんとプロフェッショナルなものになります。また、環境変数を活用してパスのハードコードを避けるという実務的なポイントも押さえておくと、自宅のPCと会社のPCを行き来するような場面でもストレスなく運用できます。

皆さんも普段使っているCLIスクリプトに数行追加して、快適なデスクトップ環境を構築してみてはいかがでしょうか。