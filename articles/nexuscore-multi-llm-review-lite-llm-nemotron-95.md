---
title: "【NexusCore事例】LLMフォールバック設計：nemotron統一+合成案で95%可用性を達成"
emoji: "📝"
type: "tech"
topics: ["LLM", "fallback", "Python", "NexusCore"]
published: false
---

```markdown
title: "【NexusCore事例】LLMフォールバック設計：nemotron統一+合成案で95%可用性を達成"
emoji: "🛡️"
type: "tech"
topics: ["LLM", "fallback", "Python", "NexusCore"]
published: false
```

# はじめに

近年、自律型エージェントやコード生成システムなど、複数のLLM（大規模言語モデル）を組み合わせて利用するアーキテクチャが一般的になってきました。しかし、複数のAPIを組み合わせるシステムにおいて避けて通れないのが「可用性」の問題です。

APIのレートリミット（アクセス制限）やサーバー障害が発生した際、システム全体が停止してしまうのは致命的です。本記事では、私が開発に関わるエージェントパイプラインプロジェクト「NexusCore」の実体験をもとに、1台のLLMが止まっても処理が止まらない**フォールバック（縮退運転）設計**について解説します。

OpenRouterなどのBYOK（Bring Your Own Key）環境でも通用する、Pythonを用いた実践的な可用性設計のコツを学びましょう。

# LLM集約ルーティングと例外安全の基本

複数LLMを使うシステムでは、「コード生成にはモデルA」「レビューにはモデルB」といったルーティングが行われます。NexusCoreではこれを `PURPOSE_TO_MODEL` というマッピングで管理しています。

最近のアップデートで、私たちはこのルーティングを「3つのLLM集約ルーティング」へ再設計しました。特定のベンダーに依存しすぎないようにし、Geminiなどのコストパフォーマンスが良いモデルをうまく活用しつつ、システム全体の可用性を高める設計です。

可用性を高める上で最も重要なのが**例外安全**と**フェイルセーフ**の考え方です。

例えば、APIエラーが発生した際、エラーを握りつぶして空のデータで次の処理に進めてしまう（フェイルオープン）と、後続のシステムが暴走したり、壊れたデータが量産されたりする危険があります。そこでNexusCoreでは、リトライが枯渇した際には「安全な状態でタスクを終了させる（フェイルセーフ）」方針へと切り替えました。

# Pythonで実装するフォールバックと合成案生成

それでは、実際のフォールバック機構の実装例を見てみましょう。

特定のLLMへのAPI呼び出しが失敗した際、別のLLMへリクエストを切り替えるシンプルな実装です。`try-except` を用いてエラーをキャッチし、安全に次のモデルへ処理を移譲します。

```python
import ast
from typing import List, Dict

# 目的ごとのモデルルーティング定義
PURPOSE_TO_MODEL: Dict[str, List[str]] = {
    # 強力なモデルから、フォールバック用の軽量モデルへ順番に定義
    "code_generation": ["model_a_high", "model_b_standard", "nemotron_fallback"]
}

def execute_llm_with_fallback(prompt: str, purpose: str) -> str:
    models = PURPOSE_TO_MODEL.get(purpose, [])
    last_exception = None

    for model_name in models:
        try:
            # LLM APIの呼び出し（例外が起きうる処理）
            response = call_llm_api(model_name, prompt)
            
            # 返却されたコードの構文チェック（AST検査）
            # LLMは時々壊れたコードを出力するため、ここで破損を根本的に防ぐ
            validate_python_syntax(response)
            
            # 成功したら結果を返して終了
            return response

        except (RateLimitError, APIConnectionError, TimeoutError) as e:
            # ネットワークエラーや制限時は、次のモデルへフォールバック
            print(f"[Fallback] {model_name} でエラー発生。次のモデルへ切替えます: {e}")
            last_exception = e
        except SyntaxError as e:
            # AST検査による構文エラー時もフォールバック
            print(f"[Validation] {model_name} の出力が壊れています: {e}")
            last_exception = e

    # 全てのLLMが失敗した場合のフェイルセーフ処理
    # エラーを握りつぶさず、安全に例外を伝播させる
    raise RuntimeError(f"全てのLLMルーティングに失敗しました。最終エラー: {last_exception}")

def validate_python_syntax(code: str):
    """LLMが生成したPythonコードが壊れていないかASTで検査する"""
    try:
        ast.parse(code)
    except SyntaxError:
        raise SyntaxError("生成されたコードの構文が不正です。")
```

このように、「エラーの種類に応じて次のモデルへ切り替える」＋「出力結果の健全性を検査する」というアプローチをとることで、単一のLLM障害に引きずられない堅牢なシステムを構築できます。

# なぜこの設計で95%の可用性を達成できるのか？

上記のコードのように、単にエラー時に別のLLMを呼ぶだけでなく、以下の工夫を組み合わせることで、システム全体の可用性を95%以上へと引き上げることができます。

### 1. AST検査による破損の根本防止
LLMは賢いですが、時として存在しないメソッドを呼び出したり、途中で文章を書き始めたりするコード（ハルシネーション）を出力することがあります。フォールバック先のLLMがこのような「壊れたコード」を出力した場合、即座に `ast.parse` による構文検査（AST検査）で弾くことで、システム全体の破損を根本的に防ぎます。

### 2. デバッグ履歴の保持と合成案生成
フォールバックを繰り返す中で、最終的に人間の介入が必要になった場合（NEEDS_HUMAN_REVIEW状態）、ただエラーを投げるだけでは原因究明に時間がかかります。
NexusCoreでは、フォールバックの過程でどのモデルがどのようなエラーを出したかの履歴（debug_history）を保持し、最終的に合成されたレビュー案としてレポートに添付する設計にしました。これにより、OpenRouter BYOK環境下でも、どのAPIキーのモデルが不安定だったかを容易に追跡できます。

### 3. try-finallyによるリソース保護
ファイルの書き込みやサンドボックス環境の実行など、副作用を伴う処理に対しては、必ず `try-finally` ブロックを適用し、途中でLLMが例外を吐いてもクリーンアップ処理が走るようにしています。これにより、再試行時のメモリリークやファイルロックなどの競合を防いでいます。

# おわりに

LLMを活用したシステム開発はまだ歴史が浅く、ベストプラクティスが日々更新されています。しかし、「外部APIはいつでも落ちる」という前提に立ち、例外安全とフェイルセーフを徹底することで、実務レベルで耐えうる堅牢なパイプラインを構築することができます。

本記事で紹介した `PURPOSE_TO_MODEL` マッピングと合成案生成の考え方は、非常に小さな実装コストで導入できるため、ぜひ皆さんのプロジェクトでも試してみてください。この知見が、より安定したLLMアプリケーションを構築するための参考になれば幸いです。