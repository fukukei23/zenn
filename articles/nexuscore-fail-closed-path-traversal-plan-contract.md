---
title: "【NexusCore事例】fail-closed設計でPath Traversalを防御：plan_contractのtarget_files検証の実装解説"
emoji: "📝"
type: "tech"
topics: ["fail-closed", "Path Traversal", "契約駆動開発", "セキュリティ", "Python"]
published: false
---

```markdown
title: "【NexusCore事例】fail-closed設計でPath Traversalを防御：plan_contractのtarget_files検証の実装解説"
emoji: "🛡️"
type: "tech"
topics: ["fail-closed", "Path Traversal", "契約駆動開発", "セキュリティ", "Python"]
published: false
---
```

## はじめに

複数のAIエージェントが協調して自律的にソフトウェア開発を進めるシステムは、開発の効率化をもたらす一方で、新たなセキュリティリスクをもたらします。

私が開発に関わっている「NexusCore」という、12のAIエージェントが協調動作する開発システムでも、エージェント間の受け渡しにおけるデータの不備が原因で、深刻な**Path Traversal（パストラバーサル）脆弱性**が露見しました。

本記事では、この危機を「契約駆動開発」と「fail-closed（フェイルクローズド）設計」を用いてどのように解決したか、具体的なPythonコードとともに解説します。AIエージェントにファイル操作を任せるシステムを構築している方にとって、必見の知見となるはずです。

## Path Traversal脆弱性とは？なぜAI開発で危険なのか

Path Traversal（ディレクトリトラバーサル）とは、攻撃者がファイル名に `../` のような特殊な文字列を含めることで、意図しないディレクトリのファイルにアクセスしたり、書き換えたりする攻撃手法です。

従来のWebアプリケーションでもよく知られた脆弱性ですが、AIエージェントがファイルを操作するシステムではより深刻なリスクになります。なぜなら、LLM（大規模言語モデル）はプロンプトインジェクションなどの影響を受ける可能性があり、悪意のある指示やハルシネーション（もっともらしい嘘）によって、システムの重要なファイル（例：`/etc/passwd` やプロジェクトの `.env` ファイルなど）を読み込んだり、上書きしたりしてしまう危険性があるからです。

NexusCoreでは、計画を立てる「Plannerエージェント」が、実装すべきファイルのパス（`target_files`）を決定し、実装を担当するエージェントがそのファイルを生成・書き換えるというフローをとっていました。しかし、初期の実装では**「Plannerが指定したパスを無条件に信頼し、そのままファイルシステムへアクセスしてしまう」**という、非常に危険な状態になっていました。

## fail-closed設計と契約駆動開発による解決

この問題を解決するため、Plannerエージェントの出力を厳格に検証する `plan_contract` というモジュールを新設し、システムに**契約駆動開発**の概念を導入しました。

ここで重要になるのが **fail-closed（フェイルクローズド）** の考え方です。これは、システムの検証に失敗した場合や異常を検知した場合、アクセスを「拒否」して安全な状態で処理を停止する（または安全なフォールバック処理に逃げる）設計方針です。

AIが出力したファイルパスが不正だった場合、それを無理やり補正して処理を続ける（fail-open）のは危険です。`plan_contract` では以下の3段構えで、堅牢な防御と安全なフォールバックを実現しました。

1. **target_files検証**: パスの形式が正しいか、プロジェクト外へ出ていないか
2. **パストラバーサル防御**: 絶対パスや `..` によるディレクトリ遡及の完全拒否
3. **劣化モードフォールバック**: 検証エラー時は即座に処理を中断し、安全なデフォルト状態に移行

## 具体的な実装：plan_contractによるtarget_files検証

実際に `plan_contract.py` に実装したPath Traversal防御のコードを見てみましょう。初心者の方にもわかりやすいよう、処理をシンプルにしています。

```python
from pathlib import Path

def validate_target_files(target_files: list[str], project_root: str) -> list[str]:
    """
    Plannerエージェントが指定したtarget_filesの安全性を検証する
    （Path Traversal防御）
    """
    safe_files = []
    # プロジェクトのルートディレクトリ（許可される範囲）を絶対パスで取得
    root_path = Path(project_root).resolve()

    for file_path in target_files:
        target = Path(file_path)

        # 1. 絶対パスやWindowsドライブレター（C:など）を拒否
        # AIがOSのシステムファイルを指定するのを防ぐ
        if target.is_absolute() or len(target.drive) > 0:
            raise ValueError(f"絶対パスは許可されていません: {file_path}")

        # 2. Path Traversal防御
        # ベースディレクトリと結合し、シンボリックリンクや ../ を解決（resolve）する
        resolved_target = (root_path / target).resolve()

        # 解決後のパスが、プロジェクトルートの配下にあるかチェック
        # 配下にない場合、ルートの外（../../etc/passwd など）へ出ようとしていると判定
        if root_path not in resolved_target.parents and resolved_target != root_path:
            raise ValueError(f"許可されていないディレクトリへのアクセスです: {file_path}")

        safe_files.append(str(target))

    return safe_files
```

### 実装のポイント：なぜ `resolve()` が重要なのか

文字列の単純な `..` の置換や、`startswith()` を使った判定は、バイパス（回避）されるリスクがあります。Pythonの `pathlib.Path.resolve()` を使用することで、シンボリックリンクの展開や `.`、`..` の解決をOSレベルで正確に行ってくれます。

解決後の絶対パス同士を比較することで、「指定されたファイルが、本当に許可されたプロジェクトフォルダの中に存在しているか」を確実に検証できます。

### 劣化モードフォールバック（fail-closedの実践）

AIの出力が空であったり、上記の検証で `ValueError` が発生した場合、システムは処理を継続しません。この状態を「契約違反」とみなし、システム全体を安全に停止させるか、人間が介入できる「劣化モード」へ強制的にフォールバックさせます。

これにより、LLMがどのようなパスを生成しようとも、システムファイルが破壊されたり機密情報が漏洩したりする事故を完全に防ぐことができます。

## おわりに

AIエージェントにファイル操作の権限を与えるシステムにおいて、**「LLMの出力を絶対にそのまま信頼しない」** ことは鉄則です。

NexusCoreの事例では、`hello.py` という固定ファイルに書き込んでいた初期状態から脱却し、動的にファイル生成を許可するようにしたことで一時的に脆弱性が生まれました。しかし、`plan_contract` による fail-closed 設計とパス検証を実装することで、安全性を担保したまま柔軟な開発パイプラインを構築できました。

「AIの自律性」を高めるほど「セキュリティの境界線」は曖昧になりがちです。契約駆動開発のような明確な検証レイヤーを挟むことで、私たちはAIと人間の安全な協調作業を実現できます。皆さんのシステムでも、AIが生成するファイルパスやコマンドが安全かどうか、一度見直してみてはいかがでしょうか。