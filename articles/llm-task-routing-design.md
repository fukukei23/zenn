---
title: "複数LLMプロバイダーのタスク自動振り分け設計（コード生成はGPT、レビューはClaude）"
emoji: "🔀"
type: "tech"
topics: ["ai", "llm", "routing", "multiagent"]
published: false
---

## はじめに

LLMプロバイダーはそれぞれ得意不得意があります。コード生成に強いモデル、推論に強いモデル、分類のような単純タスクに十分なモデル。全てのタスクを1つのモデルで処理するのは、コスト面でも品質面でも非効率です。

本記事では、タスクの性質に応じて最適なLLMを自動選択するタスク振り分けシステムの設計を紹介します。

## 2層ルーティングの全体像

```
                ユーザーのリクエスト
                       ↓
               ┌──────────────┐
               │ TaskClassifier │  ← タスク分類（軽量モデル）
               └──────┬───────┘
                      ↓
            タスク種別を判定
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   品質層（Quality）           軽量層（Lightweight）
        ↓             ↓             ↓
   GPT-5.5      Claude Sonnet    GLM-5.1
   Gemini 3.1                   MiniMax M2.7
```

## タスク分類（TaskClassifier）

### 分類の仕組み

TaskClassifierは、ユーザーのリクエストをLLMで分類し、タスク種別を判定します。

```python
class TaskClassifier:
    def classify(self, prompt: str) -> str:
        response = self.llm_client.chat(
            messages=[{
                "role": "user",
                "content": f"以下のタスクを分類:\n{prompt}"
            }],
            temperature=0.0,  # 確定的な分類
            response_format={"type": "json_object"}
        )
        task_type = response.get("task_type", "general")
        # 許可されたタスク種別のみ受理
        if task_type in self.allowed_types:
            return task_type
        return "general"  # フォールバック
```

`temperature=0.0`で確定的な分類を行い、未知のタスク種別は`general`にフォールバックします。

### タスク種別の定義

| タスク種別 | 内容 | 振り先 |
|---|---|---|
| code_generation | コードの新規生成・実装 | 品質層（GPT-5.5） |
| code_review | コードレビュー・品質評価 | 品質層（Claude Sonnet） |
| architecture | アーキテクチャ設計 | 品質層（Gemini 3.1） |
| debugging | エラー分析・修正 | 品質層（GPT-5.5） |
| classification | 分類・判定 | 軽量層（GLM-5.1） |
| summary | 要約・フォーマット | 軽量層（MiniMax M2.7） |
| general | その他 | 軽量層（GLM-5.1） |

## LLMプロファイルの定義

各プロバイダーの特性をプロファイルとして定義します。

### 品質層（Quality Tier）

高精度が求められるタスク向け。

```python
PROFILES = {
    # OpenAI: コード生成の主戦力
    "gpt_codex": {
        "provider": "openai",
        "model": "gpt-5.5",
        "temperature": 0.2,
        "max_tokens": 4096,
    },
    "gpt_strict": {
        "provider": "openai",
        "model": "gpt-5.5",
        "temperature": 0.0,  # 確定的出力
    },

    # Anthropic: レビュー・推論
    "sonnet_review": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "temperature": 0.15,
    },
    "sonnet_code": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "temperature": 0.2,
    },

    # Google: 分析・計画
    "gemini_analysis": {
        "provider": "google",
        "model": "gemini-3.1-pro",
        "temperature": 0.15,
    },
}
```

### 軽量層（Lightweight Tier）

コスト優先のタスク向け。

```python
PROFILES = {
    "glm_default": {
        "provider": "glm",
        "model": "glm-5.1",
        "temperature": 0.3,
    },
    "glm_strict": {
        "provider": "glm",
        "model": "glm-5.1",
        "temperature": 0.0,
    },
    "minimax_default": {
        "provider": "minimax",
        "model": "minimax-m2.7",
        "temperature": 0.4,
    },
    "minimax_analytical": {
        "provider": "minimax",
        "model": "minimax-m2.7",
        "temperature": 0.1,
    },
}
```

## タスク→モデルのマッピング

各タスクに、primary / secondary / fallback の3段階を設定します。

```python
TASK_MODEL_MAP = {
    "code_generation": {
        "primary": "gpt_codex",
        "secondary": "sonnet_code",
        "fallback": "glm_default",
        "temperature": 0.2,
    },
    "code_review": {
        "primary": "sonnet_review",
        "secondary": "gemini_analysis",
        "fallback": "glm_default",
        "temperature": 0.15,
    },
    "architecture": {
        "primary": "sonnet_review",
        "secondary": "gemini_analysis",
        "fallback": "glm_default",
        "temperature": 0.15,
    },
    "classification": {
        "primary": "glm_default",
        "secondary": "minimax_default",
        "temperature": 0.0,
    },
    "general": {
        "primary": "glm_default",
        "secondary": "minimax_default",
        "temperature": 0.3,
    },
}
```

primaryが利用不可（429エラー等）の場合、secondaryにフォールバックし、さらにfallbackへ遷移します。

## 予算管理（Budget Manager）

### 事前コスト見積もり

LLM呼び出しの前に、トークン数からコストを推定します。

```python
class LLMRouter:
    def estimate_cost(self, prompt_tokens, model_profile):
        rate = COST_PER_TOKEN[model_profile["provider"]]
        return prompt_tokens * rate
```

### 日次予算制限

```python
DAILY_LIMIT_DEFAULT = 5.0  # USD

def check_budget(self, estimated_cost):
    today_spend = self.get_today_spend()
    if today_spend + estimated_cost > self.daily_limit:
        # 安いモデルにフォールバック
        return self.get_cheapest_available()
    return None  # 予算内、そのまま実行
```

予算上限に近づくと、自動的に軽量層のモデルに切り替わります。

### 環境変数による強制切り替え

開発中やテスト時は、全タスクを軽量モデルに強制できます。

```bash
# 全タスクを強制的にGLMに振る
export NEXUS_FORCE_CHEAP_TASKS=true
```

## フォールバックチェーン

各プロバイダーのエラーに応じたフォールバックの流れ:

```
429 Rate Limit → 指数バックオフ → secondaryモデルに切り替え
    ↓ secondaryも429
    ↓ fallbackモデルに切り替え
    ↓ fallbackもNG
503 Service Unavailable → 人間に通知
```

リトライ回数はエラー種別で決定:

| エラー種別 | リトライ回数 | バックオフ |
|---|---|---|
| Rate Limit (429) | 5回 | 指数（1s → 2s → 4s → 8s → 16s） |
| Timeout | 3回 | 線形（1s → 2s → 3s） |
| Connection Error | 3回 | 指数（1s → 2s → 4s） |
| Invalid Output | 3回 | 線形（即時 → 1s → 2s） |
| Security Error | 0回 | 即中止 |

## コスト最適化の実測値

この2層ルーティングにより、タスクの約85%を軽量層（GLM/MiniMax）で処理しています。

```
品質層: 15%のタスク（コード生成、レビュー、設計）
軽量層: 85%のタスク（分類、要約、判定、一般チャット）
```

全タスクを品質層のモデルで処理した場合と比較して、月間コストを約70%削減できています。

## 設計上のトレードオフ

### 分類の精度 vs コスト

TaskClassifier自体もLLM呼び出しです。分類に高精度なモデルを使えば精度は上がりますが、分類のコストが増大します。

対策: 分類には軽量モデル（`gpt-4o-mini`相当）を使用。`temperature=0.0`で確定的出力にすることで、精度を確保しつつコストを最小化。

### フォールバックの品質

primary → fallback（例: GPT-5.5 → GLM-5.1）に切り替わった場合、出力品質が低下する可能性があります。

対策: フォールバック先での出力をGuardianAgentがレビューし、品質が不十分な場合は人間にエスカレーション。

## この設計の限界

- **分類ミスの影響**: タスク分類が誤ると、不適切なモデルに振り分けられる
- **モデル更新への追従**: プロバイダーがモデルを更新すると、プロファイルの再調整が必要
- **レイテンシ**: primary → secondary → fallback の遷移により、応答時間が延びる場合がある

## おわりに

複数LLMプロバイダーを活用するシステムでは、「どのタスクにどのモデルを使うか」の設計が、コストと品質の両面で重要です。

タスク分類 → プロファイル定義 → 3段階フォールバック → 予算管理の4層構造により、コストを抑えつつ必要な場面で高品質なモデルを利用できるバランスを実現しています。

### 関連記事

- [14のAIエージェントを協調させるマルチエージェントアーキテクチャの設計](https://zenn.dev/fukukei23/articles/multi-agent-orchestration-design)
- [月間27億トークンを処理したLLMルーティングの実運用レポート](https://zenn.dev/fukukei23/articles/llm-routing-one-month-report)
- [Claude Code CLIをGLM（Z.AI）で代替した話](https://zenn.dev/fukukei23/articles/claude-code-cost-optimization)
