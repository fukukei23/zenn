---
title: "【初心者向け】Claude CodeでWindows画面を自動操作：スクリーンショット・クリック・キー入力のスクリプト集"
emoji: "📝"
type: "tech"
topics: ["Windows", "Automation", "Claude Code", "Beginner"]
published: false
---

```markdown
title: "【初心者向け】Claude CodeでWindows画面を自動操作：スクリーンショット・クリック・キー入力のスクリプト集"
emoji: "🤖"
type: "tech"
topics: ["Windows", "Automation", "Claude Code", "Beginner"]
published: false
```

## はじめに

日々のIT業務において、定型作業の自動化は生産性を大きく向上させます。しかし、ブラウザ操作や特定のデスクトップアプリを立ち上げてクリックやキー入力を行うような「GUI操作」の自動化は、環境構築が難しく初心者にはハードルが高いのが現状です。

この記事では、Claude Codeの設定や運用スクリプトを管理するリポジトリ（`claude-config`）に最近追加された、Windows画面の自動操作スクリプト群をベースに、PowerShellとBash（WSL）を組み合わせた自動化の基礎を解説します。

「スクリーンショットの取得」「クリック」「キー入力」といった具体的な処理をどう実装するか、そしてIT実務でどのように活用できるのかを初心者向けにわかりやすく紹介します。

## 1. 自動化スクリプトの基礎：環境に依存しないパスの書き方

Windows環境で自動化スクリプトを書く際、つまずきやすいポイントの1つが「ファイルパス」の問題です。特にWSL（Windows Subsystem for Linux）のBashスクリプトと、WindowsネイティブのPowerShellを組み合わせる場合、ユーザー名が含まれる絶対パス（例: `/home/username/...`）をハードコードしてしまうと、別のPCに移行した際にスクリプトが動かなくなってしまいます。

最近のアップデートでは、この問題を解決するためにすべてのスクリプトからハードコードされたパスが除去されました。

**改善前（ハードコード）**
```bash
SCRIPT_PATH="/home/username/scripts/notify.sh"
```

**改善後（環境変数の利用）**
```bash
# Bashの場合
SCRIPT_PATH="$HOME/scripts/notify.sh"

# PowerShellの場合
$ScriptPath = "$env:USERPROFILE/scripts/notify.ps1"
```

このように環境変数（`$HOME` や `$env:USERPROFILE`）を利用することで、新PCへの移行時でもスクリプトをそのままコピーするだけで動作するようになり、メンテナンス性が劇的に向上します。自動化の第一歩として、この「環境の非依存化」を徹底することが重要です。

## 2. PythonとPowerShellを連携したWindows自動操作の実装

Windowsの画面操作を自動化するために、PythonからPowerShellの機能を呼び出すアプローチが非常に有効です。ここでは、具体的な実装例を紹介します。

以下のPythonスクリプトは、ユーザーのホームディレクトリを動的に取得し、Windows側のPowerShellスクリプト（スクリーンショットの取得やクリック操作を担う）をキックするラッパーの例です。

```python
import subprocess
from pathlib import Path

def get_script_path(script_name: str) -> Path:
    """ユーザー名に依存しないスクリプトのパスを取得する"""
    # Path().expanduser() を使ってチルダ (~) を展開
    base_dir = Path("~/.claude/scripts").expanduser()
    return base_dir / script_name

def execute_computer_use(action: str):
    """PowerShellスクリプトを実行してWindows画面を操作する"""
    ps_script = get_script_path(f"{action}.ps1")
    
    if not ps_script.exists():
        print(f"スクリプトが見つかりません: {ps_script}")
        return

    try:
        # PowerShellの実行ポリシーをバイパスしてスクリプトを実行
        subprocess.run(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)],
            check=True
        )
        print(f"{action} の実行が完了しました。")
    except subprocess.CalledProcessError as e:
        print(f"エラーが発生しました: {e}")

# 実行例: スクリーンショットを取得するスクリプトを実行
execute_computer_use("take_screenshot")
```

このようにPython側でロジックや例外処理を担い、実際の画面操作（マウスカーソルの移動、クリック、キー入力のエミュレート）はPowerShell（`.ps1`）に任せることで、堅牢で拡張性の高い自動化ツールを構築できます。

## 3. IT実務での活用シーン：人間の承認を伴う自動化

「画面操作の自動化」というと、完全に人間が介入しない無人運用を想像しがちですが、実務では**「自動化したいけれど、最終判断は人間が行いたい」**というケースが多々あります。

例えば、定期実行しているタスクが特定の条件を満たした際、Windowsの通知を飛ばして承認を求めるようなユースケースです。

`claude-config`の活動履歴にも、PowerShellのToast通知を利用して承認プロセスを実装した事例が見られます。

```powershell
# notify.ps1 の概念実装例
Add-Type -AssemblyName System.Windows.Forms

$notificationText = "自動化タスクが承認待ちです。確認してください。"
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.ShowBalloonTip(5000, "Automation Alert", $notificationText, [System.Windows.Forms.ToolTipIcon]::Info)
```

### 実務での具体的なフロー

1. **バックグラウンド処理**: BashやPythonスクリプトが定期的にシステムの状態を監視・操作（スクリーンショットの取得や特定のボタンクリックなど）を行います。
2. **承認要求**: 確定ボタンを押すなどの重要な操作が直前に差し掛かった際、処理を一時停止し、PowerShell経由でWindowsのデスクトップ通知を表示します。
3. **人間の判断**: 通知を見た担当者が画面（スクリーンショットや実際の画面）を確認し、問題なければ人間がクリックを実行、あるいはコマンドラインから承認コマンドを打ち込みます。

このように「Computer Use（PC操作）」と「通知」を組み合わせることで、現場のセキュリティや運用ルールに則った安全な自動化（RPA）を実現できます。

## おわりに

今回はWindows環境における自動操作スクリプトの基礎と、実務での活用アプローチについて解説しました。

ポイントは以下の3点です。
1. パスのハードコードを避け、環境変数（`$HOME`など）を活用して移植性を高めること
2. PythonやBashからPowerShellスクリプトを呼び出し、役割を分担させること
3. 全自動だけでなく、通知を活用して「人間の承認」をプロセスに組み込むこと

Claude CodeのようなAIツールの発展により、画面の自動操作（Computer Use）のハードルは大きく下がっています。まずは簡単なスクリーンショットの取得や通知から試し、日々の繰り返し作業を自動化してみてはいかがでしょうか。