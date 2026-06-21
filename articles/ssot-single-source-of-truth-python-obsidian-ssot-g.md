---
title: "【初心者向け】SSOT（Single Source of Truth）をPython+Obsidianで実装する：ssot-guideの実例から学ぶデータ管理"
emoji: "🌵"
type: "tech"
topics: ["Python", "Obsidian", "SSOT", "初心者向け", "GitHub"]
published: false
---

## はじめに

システム開発やドキュメント管理において、「最新の情報がどこにあるか分からない」という問題に直面したことはないでしょうか？要件定義書はAのツール、設計図はBのツール、ソースコードの説明は各リポジトリのREADME、そして個人のメモはローカル……と、情報があちこちに散乱してしまう現象です。

これを解決するアーキテクチャ概念が「SSOT（Single Source of Truth）」です。
本記事では、AIエージェント開発のガイドライン管理を題材に、Markdownエディタの「Obsidian」を情報の中心（SSOT）とし、PythonスクリプトでGitHub上の公開用リポジトリへ自動同期する仕組みについて、初心者の方にもわかりやすく解説します。

## 1. SSOT（Single Source of Truth）とは何か？

SSOTとは、「信頼できる唯一の情報源」を意味する設計思想です。システムアーキテクチャやデータベース設計の世界だけでなく、個人のナレッジベースやチーム内のドキュメント管理にも適用できる強力な概念です。

たとえば、あるAPIの仕様書をNotionで管理し、開発者向けの詳細ドキュメントをGitHubで管理していたとします。仕様変更があった際、両方のツールを更新しなければならず、片方の更新を忘れると「どちらが正しい情報なのか？」という情報の不整合が発生します。

SSOTの考え方に基づき、「この情報はここ（唯一の場所）で管理する」とルールを定めることで、情報の確実性が担保され、メンテナンスの手間も大幅に削減されます。

## 2. なぜObsidianをSSOTの中心に据えるのか？

今回の実例である「ssot-guide」のようなプロジェクトでは、ObsidianをSSOTのハブ（中心）として採用しています。
Obsidianは、ローカル環境に保存されるプレーンテキスト（Markdownファイル）でナレッジベースを構築できるツールです。クラウドサービスと異なり、以下のような理由からSSOTとして非常に優秀です。

- **オフライン環境と高いパフォーマンス**: サーバーと通信しないため、検索や入力が軽快です。
- **プレーンテキストの汎用性**: 独自のデータ形式ではなく標準的なMarkdown形式で保存されるため、他のシステム（Gitなど）との親和性が極めて高いです。
- **圧倒的な拡張性**: 豊富なプラグインにより、タスク管理からデータ可視化まで、自分好みのノート環境を構築できます。

私自身の実務経験からも、頭の中の思考を整理するための「個人のノート」と、チームで共有するための「公式ドキュメント」を別々のツールで管理するのは非効率です。Obsidian上で書いたメモをそのままSSOTとし、適切なフォーマットに変換して公開する仕組みがあれば、最もスムーズに情報を運用できます。

## 3. PythonでObsidianとGitHubを同期する仕組みを作る

Obsidianで書いた内容を「唯一の情報源（SSOT）」とし、それをGitHub Pagesなどで公開するための別リポジトリへ同期する仕組みを構築してみましょう。

実際の対象リポジトリのコミット履歴を見ると、以下のようなメッセージが短時間の間に複数並んでいることがわかります。

```text
sync: obsidian-ssot 70f1d41 → ssot-guide
sync: obsidian-ssot 0b45a1e → ssot-guide
```

これは、「Obsidianの管理用リポジトリ（同期元）」から「公開用リポジトリ（同期先）」へ、データが同期された痕跡です。手動でファイルをコピペするのではなく、自動的または半自動的にスクリプトが走っていることが伺えます。

この同期処理は、Pythonの標準ライブラリである `shutil`（ファイル操作）と `subprocess`（Gitコマンドの実行）を組み合わせることで、数十行のコードで実装可能です。

以下に、指定したディレクトリのファイルを同期し、Gitにコミット・プッシュするPythonスクリプトの例を示します。

```python
import subprocess
import shutil
from pathlib import Path

# パスの設定（環境に合わせて変更してください）
# SOURCE_DIR: Obsidian Vault内の公開用フォルダ
# TARGET_REPO: GitHub上で公開するリポジトリのローカルクローンパス
SOURCE_DIR = Path("/path/to/obsidian-vault/ai-agent-notes")
TARGET_REPO = Path("/path/to/ssot-guide")
TARGET_DIR = TARGET_REPO / "docs"

def sync_obsidian_to_github():
    """Obsidianの内容をGitHub公開用リポジトリへ同期する"""
    
    # 1. 公開用ディレクトリのクリアと最新ファイルのコピー
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)
    print("ファイルの同期が完了しました。")
    
    # 2. Git操作による変更の確定
    try:
        # すべての変更をステージング
        subprocess.run(["git", "-C", str(TARGET_REPO), "add", "."], check=True)
        
        # 差分があるかを確認（出力が空なら変更なし）
        status = subprocess.run(
            ["git", "-C", str(TARGET_REPO), "status", "--porcelain"],
            capture_output=True, text=True, check=True
        )
        
        if status.stdout:
            # 変更がある場合はコミットしてプッシュ
            commit_msg = "sync: obsidian-ssot -> ssot-guide"
            subprocess.run(["git", "-C", str(TARGET_REPO), "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "-C", str(TARGET_REPO), "push"], check=True)
            print("GitHubへ変更をプッシュしました。")
        else:
            print("同期すべき変更はありません。")

    except subprocess.CalledProcessError as e:
        print(f"Git操作でエラーが発生しました: {e}")

if __name__ == "__main__":
    sync_obsidian_to_github()
```

### 実装のポイントと実務上のメリット

このスクリプトの肝は、`subprocess` モジュールを使ってGitコマンドをPythonから直接実行している点です。また、`shutil.copytree` を用いてフォルダを丸ごとコピーすることで、削除されたファイルの管理も正確に行えます。

このスクリプトをCI/CDツール（GitHub Actionsなど）で定期実行したり、ローカル環境のCronで回したりすることで、以下のような圧倒的なメリットが得られます。

1. **執筆体験の向上**: 公開用リポジトリの冗長なファイル構造を気にすることなく、Obsidianの書きやすいエディタ上だけでドキュメントの執筆・修正に集中できます。
2. **不要なファイルの除外**: Obsidianには個人的なメモや日記、設定ファイルも混在します。「公開用フォルダ」だけを同期することで、情報の漏洩を防ぎつつ、必要な情報だけを公開できます。
3. **変更履歴の自動記録**: Pythonスクリプトが自動的にコミットメッセージを付与してプッシュするため、ドキュメントの変更履歴がGitHub上に時系列で綺麗に蓄積されます。

## おわりに

「情報があちこちに散らばる」という問題は、開発のスピードと品質を大きく低下させます。
本記事で紹介したように、Obsidianを「SSOT（唯一の情報源）」として中央に配置し、Pythonスクリプトで公開用リポジトリへ同期するアーキテクチャを採用すれば、情報の整合性を保ちながら、ストレスフリーなドキュメント運用が可能になります。

「情報を一箇所に集約し、自動で配信する」というSSOTの考え方は、個人開発からチーム開発まで幅広く応用が効きます。まずは小さなプロジェクトで、ObsidianとPythonを使った自動同期の仕組みを試してみてはいかがでしょうか。