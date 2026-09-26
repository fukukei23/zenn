---
title: 【Claude Code】commit巻き込み事故を3層hookで防ぐ：git-commit-scoped設計
emoji: 🛡️
type: tech
topics: [ClaudeCode, git, pre-commit, hooks, 安全設計]
published: true
---

## はじめに

Claude Codeに作業を任せていると、起きやすいのが「commit巻き込み事故」です。「このファイルだけcommitして」と依頼したつもりが、作業ツリーに残っていた別タスクの変更まで一緒にcommitされていた——こんな経験はありませんか。

私はClaude Codeの設定をバージョン管理している自分のリポジトリで、複数セッションを並走させて運用しています。エージェントが`git add -A`系のコマンドを実行すると、他セッションが編集中のファイルまで容赦なくstagedに乗ります。特にセッション締めの「まとめcommit」で無関係な変更まで sweeping に含めてしまう事故が後を絶ちませんでした。

人間のdiff確認という「注意力」に頼る防御は、並行作業が増えるほど破綻します。この記事では、巻き込み事故を仕組みで防ぐ「3層hook設計（git-commit-scoped）」を紹介します。

## 事故の構造：なぜstagedは当てにならないのか

従来のpre-commitフックは「今stagedに何があるか」しか知りません。しかし本当に検証したいのは「stagedの中身が、今回commitすべきものと一致しているか」です。この「commitすべきもの」の情報がどこにもないため、フックは黙るしかありません。

そこで発想を変えて、エージェントに「commitするファイル一覧」を事前宣言させます。宣言と実態の突合なら、機械的に検証できます。

## 3層防御の設計

### 第1層：宣言検証（宣言とstagedの突合）

エージェントはcommit前に対象パスを宣言します。pre-commitフックは宣言とstagedを突合し、過不足があれば即ブロック。「知らないうちに紛れ込んだファイル」はここで撥ねられます。

### 第2層：pathspec commit同梱

さらに`git commit -m "..." -- <対象パス>`のようにpathspecを付けたcommitを標準手順にします。pathspec付きcommitはstaging areaの状態に依存せず、指定パスのみをcommitします。他セッションがstageした変更があったとしても、構造的に混入できません。pathspecの打ち間違いは第1層の宣言突合で検出できるため、2層で相互補完になります。

### 第3層：WT_SESSION分離（並走セッションの状態汚染対策）

同一リポジトリで複数セッションが並走すると、固定パスの宣言状態は互いに上書きし合います（env汚染）。そこでセッション識別子を優先キーにして宣言状態を分離しました。セッションAの宣言がセッションBのcommit検証に混入しなくなります。

検証本体のPython実装（簡略版）はこちらです。

```python:hooks/commit_scoped.py
#!/usr/bin/env python3
"""宣言とstagedを突合するpre-commitフック（簡略版）"""
import os
import subprocess
import sys


def staged_files() -> set[str]:
    """ステージ済みファイル一覧を取得"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def declared_files() -> set[str]:
    """環境変数経由で受け取ったcommit宣言（改行区切り）"""
    raw = os.environ.get("COMMIT_DECLARED_PATHS", "")
    return {line for line in raw.splitlines() if line}


def main() -> int:
    declared = declared_files()
    if not declared:
        print("NG: commit対象の宣言がありません")
        return 1

    undeclared = staged_files() - declared
    if undeclared:
        print("NG: 宣言していないファイルがstagedに含まれています")
        for path in sorted(undeclared):
            print(f"  - {path}")
        return 1

    print(f"OK: commit-scoped検証通過（{len(declared)}ファイル）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

エージェント側の手順はシンプルです。

```bash
# 1. 宣言して
export COMMIT_DECLARED_PATHS="src/validator.py
docs/usage.md"
# 2. pathspec付きでcommitする
git commit -m "feat(hooks): 検証追加" -- src/validator.py docs/usage.md
```

## bash→Python 1本化：env渡しでインジェクション面を廃止

最初の実装はbashでしたが、運用するうちに問題が見えてきました。

- ファイル名をシェル引数として渡すため、スペースや特殊文字を含むパスでクオーティング事故が起きる（そのままインジェクション面になる）
- ロジックが複数ファイルに分散し、修正のたびに影響範囲を追うのが辛い

そこで検証をPython 1本に集約し、データはコマンドライン引数ではなく**環境変数で渡す**ように変更しました。シェルのパースを経由しないため、引用符の入れ子や単語分割の類のバグが構造的に消えます。実際に複数のLLMにコードレビューさせて20件ほど指摘を拾い、リダイレクト指定の過誤や空リストガード漏れなども潰して安定稼働しています。

また、エージェントにこの手順を守らせるため、スキルドキュメント側も「git-commit-scoped標準」へ一斉移行しました。hook（強制）と手順（誘導）の両輪が揃って、初めて運用として定着します。

## おわりに

3層の要点をまとめます。

- **第1層・宣言検証**：commit意図の宣言とstagedの突合で「紛れ込み」を検出
- **第2層・pathspec commit**：staging areaに依存しないcommitで混入を構造的に不可能化
- **第3層・WT_SESSION分離**：並走セッション間の状態汚染を隔離

一番のポイントは、「無関係な変更まで含めてしまう事故」を、事故が起きる前段階のcommit実行時点で封じたことです。人間の注意力ではなく仕組みで防つ——AIエージェントと安全に協働するための地盤として、ぜひ参考にしてください。