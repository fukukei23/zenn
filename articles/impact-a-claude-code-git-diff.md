---
title: "【impact-a実装】Claude Codeの危険操作を自動検出するgit diffパーサ設計"
emoji: "📝"
type: "tech"
topics: ["Claude Code", "静的解析", "LLM安全性", "Python"]
published: false
---

```markdown
title: "【impact-a実装】Claude Codeの危険操作を自動検出するgit diffパーサ設計"
emoji: "🛡️"
type: "tech"
topics: ["Claude Code", "静的解析", "LLM安全性", "Python"]
published: false
```

## はじめに

Claude Codeのような自律型AIコーディングエージェントは、驚くほどのスピードでコードを記述・修正してくれますが、その強力な権限ゆえに「意図しない破壊的操作（ファイルの削除、強制プッシュ、設定ファイルの破壊的変更など）」を実行してしまうリスクもはらんでいます。

そこで、私のリポジトリではAIの危険操作を自動検出し、防ぐための仕組み（`impact-a`）を実装しました。具体的には、Claude Codeの `PostToolUse` フックを活用し、ツール実行後の `git diff` を解析して危険な変更を静的検知するラッパーを作成しました。

本記事では、LLMの安全性を担保するための「git diff パーサ設計」と「危険操作（antipatterns）の検知」、そして「ユーザーへの確認UI（3択）の実装」について解説します。

## 1. PostToolUseによる変更内容のフック

Claude Codeがファイルを編集したりコマンドを実行した直後に割り込み処理を行うのが `PostToolUse` ラッパーです。

AIがツールを使用した直後、システムは自動的に `git diff --unified=0` を実行し、変更差分を取得します。`unified=0` を指定することで、変更があった行のみを最小限のコンテキストで抽出でき、後続のパーサ処理を高速化できます。

この差分テキストをパーサに渡すことで、LLMが「何をしたか」を事後的に静的解析します。

## 2. 危険操作（dangerous-ops）を検出するパーサの実装

次に、取得した差分テキストから危険な操作を見つけ出すパーサを実装します。
DANGEROUS_PATTERNSとして、システムに致命的な影響を与えるコマンドや変更のパターン（正規表現）を定義しておきます。

以下は、Pythonを用いたシンプルなgit diffパーサの実装例です。

```python
import re
from typing import List, Dict

# 危険操作のパターンを定義
DANGEROUS_PATTERNS = {
    "destructive_command": [
        r"\brm\s+-rf\b",
        r"\bgit\s+push\s+(-f|--force)\b"
    ],
    "env_destruction": [
        r"\bDROP\s+TABLE\b",
        r"\bTRUNCATE\s+TABLE\b"
    ],
}

def parse_git_diff_and_detect_dangers(diff_text: str) -> List[Dict[str, str]]:
    """
    git diffのテキストを解析し、危険操作が含まれているかを判定する
    """
    detected_dangers = []
    
    # diffの各行を解析
    for line in diff_text.splitlines():
        # 追加された行（+）または削除された行（-）のみを対象とする
        if line.startswith('+') or line.startswith('-'):
            for category, patterns in DANGEROUS_PATTERNS.items():
                for pattern in patterns:
                    # 大文字小文字を区別せずに検索
                    if re.search(pattern, line, re.IGNORECASE):
                        detected_dangers.append({
                            "category": category,
                            "line": line,
                            "message": "危険な操作の可能性があります。"
                        })
    
    return detected_dangers

# 使用例
# sample_diff = "+$ rm -rf /path/to/important/dir"
# print(parse_git_diff_and_detect_dangers(sample_diff))
```

実務においては、このパターン辞書（antipatterns）をプロジェクトの要件に合わせて拡張していきます。たとえば、インフラ構成ファイル（Terraformなど）の `force_destroy` フラグの変更や、特定のセキュリティグループの全開放などを検知対象に加えることで、チームの運用ルールに合わせた安全弁を構築できます。

## 3. 検知後のアクション：3択UIとadditionalContextの注入

危険な操作を検知した際、無条件で処理をブロックしてしまうと、ユーザーが意図的に行った正当な操作（例：古いログフォルダの削除など）まで邪魔になってしまい、開発体験が損なわれます。

そこで、パーサが危険操作を検知した場合、Claude Codeに対して追加のコンテキスト（`additionalContext`）を注入し、ユーザーに対して以下の3択を提示するUIを実装しました。

1. **そのまま実行を許可する**（ユーザーが意図した変更であると明示した場合）
2. **別の安全なアプローチに修正して再試行する**（AIに代替案を考えさせる）
3. **操作をキャンセルして停止する**

この実装により、「安全のためにAIを過剰に制限しすぎる」ことなく、かつ「知らぬ間に壊滅的なコードが実行される」事故を防ぐという、柔軟性と安全性の両立が実現できます。

## おわりに

今回は、Claude Codeの `PostToolUse` とPythonによる静的解析パーサを組み合わせた、LLMの安全性を高める仕組み（impact-a）を紹介しました。

AIエージェントがより高度な自律性を持つようになるにつれて、出力されたコードやコマンドをいかに安全に検証するか（ガードレールの設計）が、エンジニアに求められる重要なスキルになっていくと感じています。

今後は、この静的解析パーサに、別のLLMを用いた多角的なレビュー機能（マルチLLMレビューの層a/層b）を統合し、より強固な影響分析システムへと進化させていく予定です。本記事が、AIコーディングツールを安全に運用しようと考えている方の参考になれば幸いです。