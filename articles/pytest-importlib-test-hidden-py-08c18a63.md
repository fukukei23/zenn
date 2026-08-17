---
title: "【pytest】importlibモードで同名test_hidden.py競合を回避する具体的方法"
emoji: "🧪"
type: "tech"
topics: ["pytest", "Python", "テスト", "importlib"]
published: false
---

## はじめに

筆者は、複数のお題に対して「隠しテスト」を自動生成して採点するベンチマーク用のリポジトリを開発しています。お題ごとにディレクトリを分け、その中に `test_hidden.py` を配置するシンプルな設計にしたところ、pytestがテストを1件も収集できなくなりました。

原因は、**異なるディレクトリに同じファイル名 `test_hidden.py` が存在することによるimportの衝突**です。本記事では、pytestのimportlibモードに切り替えて37テスト全件を収集できるようにするまでの手順を、設定ファイル・ディレクトリ設計・落とし穴まで具体的に解説します。

## 何が起きたのか：同名テストファイルのimport衝突

ディレクトリ構造は次のようなイメージです。

```text
/path/to/repo/
├── pytest.ini
├── conftest.py
├── tasks.yaml          # お題の定義
└── hidden_tests/
    ├── task_001/
    │   └── test_hidden.py
    ├── task_002/
    │   └── test_hidden.py
    └── ...
```

`pytest` を実行すると、次のようなエラーで収集が止まりました。

```text
import file mismatch:
imported module 'test_hidden' has this __file__ attribute:
  hidden_tests/task_001/test_hidden.py
which is not the same as the test file we want to collect:
  hidden_tests/task_002/test_hidden.py
```

pytestのデフォルトのimportモードは `prepend` です。このモードでは、`__init__.py` のないディレクトリにあるテストファイルは**ベースファイル名（この場合は `test_hidden`）がそのままモジュール名**になります。最初に読み込んだ `task_001` のテストだけが `sys.modules` に登録され、以降の同名ファイルは「別ファイルなのに同名モジュール」として衝突する、という仕組みです。

エラーのHINTに従って `__pycache__` を削除しても再発します。キャッシュの問題ではなく構造的な問題だからです。

対処策は主に2つあります。

1. 各ディレクトリに `__init__.py` を置いてパッケージ化する（prependモードのまま）
2. importモードを `importlib` に切り替える

筆者のケースでは隠しテストのディレクトリをお題の数だけ自動生成するため、テンプレートの置き忘れで `__init__.py` が欠けるリスクを避けたいと考え、**ファイル名の重複を許容できるimportlibモードを選びました**。

## 解決：pytest.iniでimportlibモードを有効にする

リポジトリのルートに `pytest.ini` を作成します。

```ini
[pytest]
addopts = --import-mode=importlib
testpaths = hidden_tests
```

importlibモードでは、テストファイルが**rootdirからの相対パスを考慮した一意なモジュール名**で読み込まれます。そのため `__init__.py` がなくても、`hidden_tests/task_001/test_hidden.py` と `hidden_tests/task_002/test_hidden.py` が共存できます。

ここで重要なのが、**iniファイルを必ずリポジトリのルートに置くこと**です。pytestはiniファイルのあるディレクトリをrootdirとして認識します。rootdirが定まらないと、コマンドを実行した場所によってモジュール名の基準が変わり、収集結果が不安定になります。

この設定を追加した結果、`pytest --collect-only -q` が正常に完了し、37テスト全件が収集されるようになりました。

## 落とし穴：sys.pathが追加されなくなる問題とconftest設計

importlibモードには副作用があります。prependモードではテストファイルのディレクトリが自動的に `sys.path` の先頭に追加されていましたが、**importlibモードではそれが行われません**。テストファイルと同じ階層にある通常のモジュールをimportしていると、`ModuleNotFoundError` に変わるケースがあります。

対応は2通りあります。

まず、conftest.pyで明示的にパスを追加する方法です。

```python
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
```

もう一つは、pytest 8.4以降で使えるiniオプション `prepend_sys_path` です。importlibモードのまま、指定したパスを `sys.path` に追加できます。

```ini
[pytest]
addopts = --import-mode=importlib
prepend_sys_path = .
testpaths = hidden_tests
```

あわせて、共通フィクスチャはリポジトリ直下の `conftest.py` に集約しました。conftestは配下のテストディレクトリから自動的に読み込まれるため、お題ごとに生成するテンプレートの中身を最小化できます。「**テストの収集はrootdir基準、importの解決はconftestで制御**」と分担を明確にすると、ディレクトリを量産するタイプの設計でも運用が安定します。

なお、importlibモードを使っていても `__init__.py` を併用できます。衝突しないので、パッケージとしての名前解決が必要な場合だけ置けば十分です。

## おわりに

- 同名テストファイルの衝突は、prependモードの「ベースファイル名＝モジュール名」という挙動が原因
- `pytest.ini` で `--import-mode=importlib` を指定し、rootdirをリポジトリルートに固定すれば衝突を解消できる
- importlibモードは `sys.path` を自動追加しないので、conftest.pyでのパス追加か `prepend_sys_path` で補う

お題ごとにテストを量産する設計では、同名ファイルは避けられない前提で仕組み側を整えるのが現実的です。同じエラーで詰まった方は、まず `pytest --collect-only -q` で収集状況を確認しつつ、本記事の設定を試してみてください。