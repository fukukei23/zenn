---
title: "【初心者向け】2リポジトリ自動同期パイプライン設計：obsidian-ssot→ssot-guideの実装例"
emoji: "🔄"
type: "tech"
topics: ["GitHubAPI", "Git操作", "自動化", "Python"]
published: false
---

## はじめに

日々のメモや技術ドキュメントをObsidianなどのMarkdownエディタで書き、それをGitHubリポジトリで管理している方は多いのではないでしょうか。

私は現在、個人のナレッジベースであるObsidian用リポジトリと、公開・AI活用用のGitHubリポジトリ（今回は `ssot-guide` と呼びます）の間で、**毎日20回以上の自動同期**を行うパイプラインを構築し、運用しています。

よくあるGitHub Actionsを使った定期コミットとは異なり、今回は「**Git Blob操作とGitHub APIを組み合わせたPush型同期**」というアプローチをとっています。

この記事では、なぜそのような高頻度な同期が必要だったのかという思想的背景と、Pythonを使った具体的な実装例を初心者の方にもわかりやすく解説します。

---

## なぜ毎日20回も同期するのか？（SSOTの思想）

そもそも、なぜわざわざ2つのリポジトリに分け、さらにそれを毎日20回も同期させるのでしょうか？

ここには**SSOT（Single Source of Truth：信頼できる唯一の情報源）**という考え方があります。

私の運用では、手元のObsidianリポジトリがあらゆる情報の「マスター（SSOT）」です。思いついたこと、エラーの解決策、AIエージェントへの指示など、すべてをとりあえずObsidianに書き込みます。

そして、`ssot-guide` リポジトリは、その情報を外部に公開したり、CI/CDを回したり、AIに読み込ませたりするための「公開用の姿」です。

思考は常に流れており、1日に何十回もドキュメントが更新されます。**「書き留めた瞬間」に即座に公開用リポジトリへ反映されてほしい**。執筆作業と公開作業の間にラグを作りたくない、というのが高頻度同期の最大のモチベーションです。

しかし、毎日20回以上も手動で `git push` をするのは非人道的です。また、後述するように通常のGitの操作方法では、この要件を満たすのが難しいという技術的な理由がありました。

## 従来のクローン方式の限界とPush型同期のメリッド

自動同期を作る際、初心者の方が真っ先に思いつくのは「サーバーにリポジトリをクローンし、ファイルをコピーして、`git commit` & `git push` する」という方法だと思います（Pull型同期）。

しかし、この方法には以下のような課題があります。

1. **コンフリクト（競合）のリスク**: 高頻度で同期をかける場合、リポジトリの状態を常に最新に保つ必要があり、わずかなタイムラグで競合が発生し、パイプラインが止まってしまいます。
2. **リソースの消費**: 単に数個のMarkdownファイルを更新したいだけなのに、毎回リポジトリ全体（`.git` の履歴含む）をクローンするのは時間も容量も無駄になります。

そこで私は、ローカルにリポジトリを持たず、**GitHub APIを直接叩いてファイルを更新する「Push型同期」**を採用しました。これにより、競合を恐れることなく、超軽量かつ高速にファイルの差分を反映できるようになります。

## Git Blob操作とGitHub APIによる実装

GitHub APIを使ってファイルを更新する場合、標準のREST API（`PUT /repos/{owner}/{repo}/contents/{path}`）を使う方法が一般的です。しかし、今回はよりGitの内部構造に近い**Git Database API（Blob・Tree・Commitを直接操作するAPI）**を使用します。

### Gitの内部構造の基礎知識

Gitの裏側（データ構造）は以下の3つの要素で成り立っています。

- **Blob（ブロブ）**: ファイルの中身（テキストデータ）本体。ファイル名は持たない。
- **Tree（ツリー）**: ディレクトリ構造。どのファイル名（パス）に、どのBlobが紐づくかを管理する。
- **Commit（コミット）**: 特定のTreeのスナップショットと、親コミットへの参照を持つ。

つまり、「ファイルの中身をBlobとして作成」→「既存のTreeに新しいBlobをぶら下げる」→「新しいTreeでコミットを作成」という手順を踏むことで、完全にGitコマンドを使わずに更新ができるのです。

### Pythonでの実装例

Pythonの `PyGithub` ライブラリを使うと、この一連の操作を直感的に記述できます。以下に、ObsidianのファイルをGitHubへ同期する具体的なコード例を示します。

```python
import os
from github import Github, InputGitTreeElement

# 環境変数からトークンを取得
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = "your-account/ssot-guide" # 自分のリポジトリ名に置き換え
BRANCH_NAME = "main"

def sync_obsidian_to_github(local_file_path, repo_file_path, commit_message):
    # GitHubクライアントの初期化
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)

    # 1. ローカルのファイルの中身を読み込む
    with open(local_file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # 2. Git Blobを作成（ファイルの実体をGitHubに送信）
    # encoding='utf-8' を指定することで日本語も文字化けせずに登録できます
    blob = repo.create_git_blob(content=content, encoding='utf-8')
    print(f"Created Blob SHA: {blob.sha}")

    # 3. 現在の最新コミットとツリー（ディレクトリ構造）を取得
    ref = repo.get_git_ref(f"heads/{BRANCH_NAME}")
    parent_commit = repo.get_git_commit(ref.object.sha)
    base_tree = repo.get_git_tree(parent_commit.tree.sha)

    # 4. 新しいツリー要素を作成（パスとBlobを紐付ける）
    # mode はファイルの場合 '100644', type は 'blob' を指定します
    element = InputGitTreeElement(
        path=repo_file_path, 
        mode="100644", 
        type="blob", 
        sha=blob.sha
    )

    # 5. 既存のツリーをベースに、新しい要素を追加した新しいツリーを作成
    new_tree = repo.create_git_tree([element], base_tree=base_tree)

    # 6. 新しいツリーを使ってコミットを作成
    new_commit = repo.create_git_commit(
        message=commit_message,
        parents=[parent_commit],
        tree=new_tree
    )

    # 7. ブランチの参照（ポインタ）を新しいコミットに強制的に向ける
    ref.edit(sha=new_commit.sha)
    print(f"Successfully synced to {REPO_NAME}!")

# 実行例
if __name__ == "__main__":
    # パスは汎用的なものを指定します
    sync_obsidian_to_github(
        local_file_path="/path/to/obsidian/note.md",
        repo_file_path="docs/note.md",
        commit_message="sync: obsidian-ssot -> ssot-guide"
    )
```

このスクリプトを実行すると、リポジトリをクローンすることなく、一瞬で対象のファイルが更新されます。実際のコミットログを見ると、`sync: obsidian-ssot → ssot-guide` というメッセージが1時間に何度も記録されているのがわかります。

## おわりに

今回は、ObsidianとGitHub間で高頻度の同期を実現するためのPush型パイプライン設計について解説しました。

Gitの内部構造（Blob, Tree, Commit）を理解し、GitHub APIを直接操作することで、コンフリクトのリスクを避けつつ、爆速で安全な自動同期環境を構築できます。

「思考をアウトプットに即座に変換したい」「複数リポジトリ間のSSOT運用を自動化したい」という方は、ぜひこのPush型同期のアプローチを試してみてください。日々の開発・執筆体験が劇的に変わるはずです！