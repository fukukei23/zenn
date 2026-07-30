---
title: "【実例解説】Auto sync定期実行の設計思想：cron vs GitHub Actionsから学ぶCI/CDミニマム導入"
emoji: "🔄"
type: "tech"
topics: ["CI/CD", "cron", "定期実行", "初心者向け", "スクリプト管理"]
published: false
---

## はじめに

皆さんは、ローカル環境の細かな変更（設定ファイルの微調整や、メモの追記など）をこまめにリモートリポジトリへ反映していますか？
「作業終わりにまとめてpushする」という手順を踏むのも良いですが、うっかり忘れてしまうことも多くあります。

私が管理しているある設定ファイル用のリポジトリでは、コミット履歴を見ると1日に何度も「Auto sync」というメッセージが記録されています。

```bash
Auto sync: 2026-07-30 10:12:11
Auto sync: 2026-07-29 21:06:22
Auto sync: 2026-07-28 22:29:17
```

このように、作業中の手間を省くために**自家製スクリプトによる定期実行（Auto sync）**を導入しました。
本記事では、初心者がいきなりGitHub Actionsなどの高度なCI/CDツールに飛びつく前に、ローカルの`cron`やスクリプトで「ミニマムな定期実行」を実現するアプローチを解説します。

## なぜGitHub Actionsではなく、自家製スクリプト（cron）を選んだのか？

「定期実行」と聞くと、真っ先にGitHub Actionsの`schedule`（cron構文）を思い浮かべる方が多いでしょう。しかし、ローカル環境の設定ファイルを同期したい場合、GitHub Actionsには以下のようなハードルがあります。

1. **ローカルの未追跡ファイルをpushできない**: CI/CDはあくまでリモートの仮想環境上で動くため、手元のPCにしか存在しない最新のファイルを直接同期するのが難しい。
2. **学習コストとセットアップの手間**: YAMLファイルを書き、権限を設定し、動作検証をするのは初心者にとって少し重い。

そこで今回は、PC起動中にバックグラウンドで定期的に`git commit`と`git push`を実行する自家製スクリプトを書くという選択をとりました。これは「CI/CDのミニマム導入」とも言えるアプローチです。

### ハードコードを避けるスクリプト設計の工夫

スクリプトを作る上で最も注意すべきは「環境依存」です。
別PCへの移行やWSL環境での実行など、環境が変わることはよくあります。

実際の開発でも「すべてのスクリプト・設定ファイルからハードコードされたパスを除去し、環境変数（`$HOME`など）に置き換えた」という改善を行いました。これにより、ユーザー名が変わったり別のPCに移行したりしても、スクリプトをそのままコピーするだけで動作するようになります。

## Pythonで実現するミニマムなAuto syncスクリプト

では、実際にAuto syncを実現しているPythonスクリプトの簡易版を見てみましょう。
ここでは、指定したディレクトリの差分をチェックし、変更があれば自動でコミット・プッシュまで行う処理を記述しています。

```python
import subprocess
from pathlib import Path
from datetime import datetime

def auto_sync(repo_path: str):
    # 環境変数などを活用し、汎用的なパス指定にする（ハードコードNG）
    target_dir = Path(repo_path).expanduser()
    
    # まずはすべての変更をステージングに上げる
    subprocess.run(["git", "-C", str(target_dir), "add", "."], check=True)
    
    # 差分があるか確認（終了コード 0 = 差分なし, 1 = 差分あり）
    diff = subprocess.run(
        ["git", "-C", str(target_dir), "diff", "--cached", "--quiet"]
    )
    
    # 差分がなければ終了
    if diff.returncode == 0:
        print("No changes to sync.")
        return

    # コミットメッセージを日時で自動生成
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto sync: {now}"
    
    try:
        # コミットしてプッシュを実行
        subprocess.run(["git", "-C", str(target_dir), "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "-C", str(target_dir), "push"], check=True)
        print(f"Successfully synced: {commit_msg}")
    except subprocess.CalledProcessError as e:
        print(f"Sync failed: {e}")

# 実行例
if __name__ == "__main__":
    # パスは実行環境の環境変数などから動的に取得するのがベストプラクティス
    auto_sync("/path/to/your/config_repo")
```

**ポイント**:
- `subprocess` モジュールを使い、PythonからGitコマンドを操作しています。
- `Path().expanduser()` を使うことで、`~` などのチルダ展開に対応させ、PC間のユーザー名の差異を吸収しています。
- `git diff --cached --quiet` を使うことで、差分がない場合に無駄な空コミットを生成しないようにしています。

このスクリプトをOSのタスクスケジューラ（Linux/Macなら`cron`、Windowsならタスクスケジューラ）に登録し、1時間おきなどに実行すれば、立派なAuto syncシステムの完成です。

## cron vs GitHub Actions：利点と欠点の比較

ローカルスクリプト（cron）とCI/CDツール（GitHub Actions）は、それぞれ適した用途が異なります。実際の運用を通じて感じたそれぞれの利点と欠点を比較してみましょう。

| 観点 | ローカルスクリプト（cron等） | GitHub Actions (CI/CD) |
| :--- | :--- | :--- |
| **実行環境** | 自分のPC上（ローカル） | GitHub側の仮想環境 |
| **適した用途** | ローカルファイルの自動バックアップ、設定の同期 | デプロイ、テストの自動化、クローラリング |
| **メリット** | 導入が簡単。ローカルの未追跡ファイルもそのままpush可能 | PCの電源が切れていても動く。GitHub上でログ確認が楽 |
| **デメリット** | PCを閉じている間は動かない。ローカル環境のPython等に依存する | 設定ファイル（YAML等）の学習が必要。外部連携の設定が面倒 |

初心者の場合、「まずは手元で動く自動化を体験する」ことが非常に重要です。
実際にスクリプトを書いて「コミット履歴が勝手に増えていく」のを見るのはとても楽しい体験ですし、今後本格的なCI/CDを学ぶ際の大きな礎になります。

## おわりに

今回は、ローカルの設定ファイルを自動で同期するための「Auto sync」の仕組みを解説しました。

GitHub Actionsをいきなり書くのはハードルが高いと感じている方は、まずは自作のPythonスクリプトと`cron`を使ったミニマムな定期実行から始めてみてはいかがでしょうか。
「ハードコードを避ける」「差分がない場合はコミットしない」といった、スクリプトを書く上での基本的なベストプラクティスも身につくので一石二鳥です。

皆さんもぜひ、自分にとって「ちょっと面倒」な作業をミニマムな自動化で解決してみてください！