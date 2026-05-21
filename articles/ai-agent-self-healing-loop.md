---
title: "AIエージェントの自己修復ループ設計（テスト失敗→原因分析→自動修正の実装）"
emoji: "🔄"
type: "tech"
topics: ["ai", "multiagent", "selfhealing", "testing"]
published: false
---

## はじめに

AIにコードを生成させると、必ずエラーが起きます。テストが失敗したり、想定と違う挙動をしたり。人間がエラーを確認して修正指示を出すのは手間がかかります。

本記事では、テスト失敗を自動検知し、原因を分析し、修正を生成し、再テストする「自己修復ループ」の設計と実装を紹介します。

## 自己修復ループの全体像

```
テスト実行
    ↓
成功 → 次フェーズへ
    ↓
失敗 → DebuggerAgent: エラー分析 + 修正パッチ生成
    ↓
パッチ適用 → 再テスト
    ↓
成功 → PostmortemAgent: 知識ベース更新
    ↓
失敗（リトライ上限） → 人間に通知
```

3つのエージェントが連携して自己修復を実現します。

- **DebuggerAgent**: エラー分析と修正パッチ生成
- **PostmortemAgent**: 失敗の根本原因分析と知識蓄積
- **GuardianAgent**: 修正後のコードレビュー

## DebuggerAgent: エラー分析と修正生成

### 処理フロー

1. テスト失敗の出力（stdout/stderr）を受け取る
2. ローカル知識ベースで既知の解決策を検索
3. 既知なら即座に適用、未知ならLLMで分析
4. 統一差分形式（unified diff）でパッチを生成

### 知識ベースの活用

DebuggerAgentは、過去の失敗から学習した知識ベースを参照します。

```python
# 知識ベースの構造
{
    "error_signature": "ImportError: No module named 'src.nexuscore'",
    "pattern": "ImportError.*No module named",
    "solution": {
        "description": "PYTHONPATHにsrc/が含まれていない",
        "fix_type": "config",
        "target": "both"
    }
}
```

エラーメッセージを正規表現でマッチングし、過去に解決済みの問題なら即座に修正案を提示します。これにより、同じエラーで何度もLLMに問い合わせるコストを削減できます。

### パッチ生成

LLMが生成する修正は、統一差分形式で出力されます。

```diff
--- a/src/nexuscore/core/retry_policy.py
+++ b/src/nexuscore/core/retry_policy.py
@@ -42,7 +42,7 @@
-    max_retries = env_int("MAX_RETRIES", default=5)
+    max_retries = _env_int("MAX_RETRIES", default=5)
```

相対パスで出力することで、リポジトリのどの位置からでも適用可能にしています。

### Auto-PR機能

修正が生成されたら、自動的にGitHub PRを作成することも可能です。 DebuggerAgentはブランチの作成、コミット、PR生成までを一括で実行できます。

## PostmortemAgent: 失敗からの学習

### 3段階のサニタイズ

PostmortemAgentに渡す入力は、3段階のサニタイズを経ます。

1. **truncate**: コンテキスト上限に合わせて切り詰め
2. **redact**: APIキーやシークレットをマスキング
3. **validate_and_normalize**: JSON正規化と文字エンコーディング検証

LLMに過剰に長いコンテキストを渡さないことと、機密情報の漏洩防止が目的です。

### エラーシグネチャの生成

PostmortemAgentは、エラーから一意の「シグネチャ」を生成します。

```
入力: ImportError: No module named 'src.nexuscore.core.errors'
シグネチャ: "ImportError:module-not-found:src.nexuscore.*"
```

正規表現パターンに変換することで、同一でなくても同種のエラーをマッチングできます。

### 3つの出力

1. **error_signature**: 正規表現パターン。次回のDebuggerAgentが照合に使用
2. **root_cause**: なぜエラーが起きたかの分析
3. **solution_pattern**: 推奨される解決策。修正タイプ（config/code/test）と対象ファイルを含む

```json
{
    "error_signature": "AssertionError.*expected.*but got",
    "root_cause": "テストの期待値が実装の変更に追いついていない",
    "solution_pattern": {
        "fix_type": "test",
        "target": "test_file",
        "description": "実装に合わせてテストの期待値を更新"
    }
}
```

## 知識の蓄積サイクル

```
エラー発生
    ↓
DebuggerAgent: 既知の解決策を検索 → なし
    ↓
LLMで分析・修正生成 → パッチ適用 → 解決
    ↓
PostmortemAgent: エラーシグネチャ + 解決パターンを生成
    ↓
知識ベースに保存（JSON）
    ↓
次回 同種エラー発生時 → DebuggerAgentが知識ベースから即座に解決
```

2回目以降はLLM呼び出しなしで解決できるため、コストと時間を大幅に削減できます。

## 設計上の工夫

### リトライ上限の設定

無限ループを防ぐため、自己修復のリトライには上限を設けています。

```python
DECISION_TABLE = {
    ModelRateLimitError: {"max_attempts": 5, "backoff": "exponential"},
    ModelTimeoutError:   {"max_attempts": 3, "backoff": "linear"},
    SandboxSecurityError: {"max_attempts": 0, "backoff": "none"},  # 即中止
}
```

エラーの種類によってリトライ回数とバックオフ戦略を変えています:
- **429レート制限**: 指数バックオフで5回まで（回復の可能性が高い）
- **タイムアウト**: 線形バックオフで3回まで
- **セキュリティエラー**: 即中止（リトライすべきでない）

### エラー分類の階層

エラーは大きく2つに分類されます。

- **リトライ可能**: レート制限、タイムアウト、接続エラー、不正な出力
- **リトライ不可**: サンドボックス実行エラー、セキュリティ違反、パッチ適用失敗、予期しないシステムエラー

リトライ不可のエラーは、即座に人間に通知します。

### コンテキストの最適化

LLMに渡すコンテキストは、最大トークン数に制限を設けています。PostmortemAgentの`_truncate`メソッドで、エラー出力が長すぎる場合は重要な部分（スタックトレースの末尾等）を優先して残します。

## 実際の動作例

### ケース: Import エラー

```
1. TesterAgent: テスト実行 → ImportError発生
2. DebuggerAgent: 知識ベース検索 → 該当なし
3. DebuggerAgent: LLMで分析 → PYTHONPATH設定ミスと特定
4. パッチ生成: CI設定ファイルのPYTHONPATH修正
5. 再テスト → 成功
6. PostmortemAgent: エラーシグネチャ "ImportError:module-not-found" を保存
7. 次回以降: 同種エラーを知識ベースから即座に解決
```

### ケース: テスト期待値のズレ

```
1. TesterAgent: テスト実行 → AssertionError: expected 200 but got 404
2. DebuggerAgent: 知識ベース検索 → 該当なし
3. DebuggerAgent: LLMで分析 → ルーティング設定の変更がテストに反映されていない
4. パッチ生成: テストファイルの期待値を更新
5. 再テスト → 成功
6. PostmortemAgent: "AssertionError.*expected.*but got" シグネチャを保存
```

## この設計の限界

- **知識ベースの肥大化**: 長期運用で知識ベースが大きくなり、検索コストが増大する
- **誤修正のリスク**: LLMが生成するパッチが必ずしも正しいとは限らない（GuardianAgentで2重チェック）
- **コンテキストの制約**: 大規模なエラー出力は、LLMのコンテキスト窓に収まらない場合がある

## おわりに

自己修復ループの核心は「失敗を知識に変えること」です。エラーを単にリトライするだけでなく、その原因と解決策を構造化して保存することで、システムが徐々に賢くなります。

DebuggerAgent（修正）→ PostmortemAgent（学習）→ 知識ベース（蓄積）の3層構造により、同じエラーに対する対応コストを段階的にゼロに近づけていくことができます。

### 関連記事

- [14のAIエージェントを協調させるマルチエージェントアーキテクチャの設計](https://zenn.dev/fukukei23/articles/multi-agent-orchestration-design)
- [Mutation Testingでテスト品質を測る](https://zenn.dev/fukukei23/articles/mutation-testing-mutmut-practice)
- [LLMのハルシネーションを構造的に防ぐプロンプト設計](https://zenn.dev/fukukei23/articles/ai-code-review-prompt-hallucination)
