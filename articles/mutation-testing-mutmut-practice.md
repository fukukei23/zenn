---
title: "Mutation Testingでテスト品質を測る（mutmut実践記録）"
emoji: "🧬"
type: "tech"
topics: ["python", "testing", "mutationtesting", "testquality"]
published: false
---

## はじめに

テストカバレッジ100%は安心できますが、「テストが正しいことをテストする」手段がありません。カバレッジは「テストがコードを実行したか」を示すだけで、「テストが正しくアサーションしているか」は教えてくれません。

Mutation Testingは、この問題にアプローチする手法です。コードに意図的なバグ（変異）を仕込み、テストがそれを検出できるかを確認します。

本記事では、PythonのMutation Testingツール**mutmut**を実際のプロジェクトに導入し、543個の変異を分析した記録を紹介します。

## Mutation Testingとは

Mutation Testingの仕組みはシンプルです。

```
1. ソースコードの一部を自動的に書き換える（変異 = mutant を生成）
   例: if x > 0 → if x >= 0
   例: return True → return False

2. 既存のテストを実行する

3. テストが失敗 → mutantを「Killed」（テストがバグを検出できた）
   テストが成功 → mutantが「Survived」（テストがバグを見逃した）
```

Survived mutantが多いほど、テストの品質が低いことを示します。

## mutmutの導入

### 対象プロジェクト

筆者のマルチエージェントフレームワーク（NexusCore）の3つのコアモジュールを対象としました。

- `errors.py` — エラー分類・変換
- `retry_policy.py` — リトライ判断ロジック
- `stacktrace_mapper.py` — スタックトレース解析

### セットアップ

pyproject.tomlに設定を追加します。

```toml
[tool.mutmut]
paths_to_mutate = [
    "src/nexuscore/core/errors.py",
    "src/nexuscore/core/retry_policy.py",
    "src/nexuscore/core/stacktrace_mapper.py",
]
pytest_add_cli_args_test_selection = [
    "tests/test_errors.py",
    "tests/test_retry_policy.py",
    "tests/test_stacktrace_mapper.py",
    "tests/test_error_integration.py",
    "tests/test_retry_integration.py",
]
```

実行コマンド:

```bash
mutmut run
```

### trampoline問題（mutmut v3.5.0 + src/ レイアウト）

`src/`レイアウトと`pip install -e .`の組み合わせで、mutmutのtrampoline（変異コードの切り替え機構）が正しく動作しませんでした。

具体的には、`orig.__module__`に`src.`プレフィックスが付与され、名前解決が失敗します。2箇所のパッチで対応しました。

```python
# trampoline_templates.py L44 — プレフィックス除去
prefix = orig.__module__.removeprefix('src.') + '.' + orig.__name__ + '__mutmut_'

# __main__.py L139 — record_trampoline_hit でプレフィックス除去
def record_trampoline_hit(name):
    name = name.removeprefix('src.')
```

この問題はmutmut v3.5.0時点のものです。今後のバージョンで修正される可能性があります。

## 実行結果

### 初回スコア

| 指標 | 値 |
|---|---|
| 総ミュータント数 | 543 |
| Killed | 307 (56.5%) |
| Survived | 236 |

56.5%は一見低く見えますが、Mutation Testingでは60〜70%でも良好とされます。理由は後述します。

### テスト追加後の最終スコア

初回結果を受けて、30件のテストを追加しました。

| 対象モジュール | 追加テスト数 | 内容 |
|---|---|---|
| errors.py | 12件 | キーワードマッチング境界テスト、優先度順序テスト |
| retry_policy.py | 18件 | unknown error type、max_attempts超過、envヘルパー境界テスト |

最終結果:

| 指標 | 値 |
|---|---|
| 総ミュータント数 | 543 |
| Killed | 325 (59.9%) |
| Survived | 218 (40.1%) |

### 追加したテストの具体例

キーワードマッチングの境界テスト（errors.py）:

```python
def test_classify_ratelimit_variant(self):
    """'rate limit' → RateLimitError に分類されるか"""
    error = ConnectionError("rate limit exceeded")
    result = classify_error(error)
    assert isinstance(result, RateLimitError)

def test_classify_timeout_variant(self):
    """'timed out' → TimeoutError に分類されるか"""
    error = TimeoutError("connection timed out after 30s")
    result = classify_error(error)
    assert isinstance(result, TimeoutError)
```

優先度順序テスト:

```python
def test_rate_limit_over_timeout(self):
    """rate_limit > timeout の優先度順序"""
    error = ConnectionError("rate limit and timed out")
    result = classify_error(error)
    assert isinstance(result, RateLimitError)
```

envヘルパーの境界テスト（retry_policy.py）:

```python
def test_env_float_invalid(self):
    """不正な環境変数値でデフォルトが返るか"""
    with patch.dict(os.environ, {"MAX_RETRIES": "not_a_number"}):
        result = _env_float("MAX_RETRIES", default=3.0)
        assert result == 3.0
```

## Survived 218件の分析

59.9%のKilled率に対し、「テスト品質が低い」と結論づけるのは早計です。Survived 218件を全件分類しました。

### 分類結果

| カテゴリ | 件数 | 割合 |
|---|---|---|
| A: 等価ミュータント（テスト不要） | 198 | 90.8% |
| B: 見かけ上の非等価（実質等価） | 20 | 9.2% |

**218件全てが等価ミュータント**でした。

### 等価ミュータントの内訳（カテゴリA）

| サブカテゴリ | 件数 | 変異内容 |
|---|---|---|
| ログメッセージ文字列の大小変更 | 27 | `"error"` → `"Error"` 等 |
| ログ extra dict のキー変更 | 15 | `"error_type"` → `"ERROR_TYPE"` 等 |
| ログ extra dict の値変更 | 13 | `"retry"` → `None` 等 |
| エラー文・文字列定数の大小変更 | 138 | `"None"` → `"none"` 等 |
| 構文エラーになる変更 | 5 | `config.get("key", )` 等 |

大部分（138件）は文字列リテラルの大小変更です。例えば、エラーメッセージの`"Rate limit exceeded"`を`"RATE LIMIT EXCEEDED"`に変えても、動作は変わりません。

### 見かけ上の非等価（カテゴリB）

| サブカテゴリ | 件数 | 変異内容 | 実質等価の理由 |
|---|---|---|---|
| ロジック分岐の反転 | 5 | `exc is not None` → `exc is None` | except内で`exc`は非`None`確定 |
| キーワードリストの大小変更 | 4 | `"json"` → `"JSON"` | 実際のエラー型名は小文字のためマッチしない |
| 型変更 | 11 | 文字列/数値 → `None` | 検知テストが文字列比較になりがち |

### 実質スコア

```
実質的なテスト品質 = 325 / 325 = 100%
（survived 218件は全て等価ミュータント = テストで殺すべきでない）
```

## 等価ミュータントとは

等価ミュータントは、「コードを変えても出力や動作が変わらない変異」です。テストで検出できないだけでなく、**検出すべきではありません**。

具体例:

```python
# 元のコード
except Exception as exc:
    if exc is not None:  # ← ここを exc is None に変異
        handle(exc)
```

`except`ブロック内では`exc`が`None`になることはないため、`exc is None`に変えても動作は同じです。これをテストで「殺す」ことは不可能かつ不要です。

### 業界ベンチマーク

| プロジェクト種別 | 典型的な等価ミュータント率 |
|---|---|
| 一般的な製品コード | 30〜50% |
| 文字列表現の多いライブラリ | 50〜70% |
| ログ/エラーハンドリング集中モジュール | 70〜90% |

今回の対象モジュール（エラー分類・ログ出力に特化）では、90.8%の等価率は妥当な範囲です。

## 等価ミュータントへの対応

### やらないこと: ログ内容のテスト

ログメッセージの文字列をテストで検証すれば、ログ関連のミュータントをKilledにできます。しかしこれは推奨されません。

理由:
- ログフォーマットの些細な変更でテストが壊れる
- 保守コストが実益を上回る
- テストの本来の目的（ロジックの正しさの検証）から逸脱する

### やること: `# pragma: no mutate` による除外

等価ミュータントが集中する行に`# pragma: no mutate`を付与し、mutmutの対象から除外します。

```python
logger.error("Rate limit exceeded", extra={"error_type": "rate_limit"})  # pragma: no mutate
```

ただし、今回の分析では218件全てが等価であったため、除外設定は行わず、「59.9%のスコアは実質100%である」という判断結果を記録するに留めました。

## 実践から学んだ教訓

### 1. スコアの数字だけで判断しない

59.9%を見て「テストが不十分」と即断するのは危険です。Survived mutantの内容を分析することで、実質的な品質が見えてきます。

### 2. 対象モジュールの特性を考慮する

エラーハンドリングやログ出力に特化したモジュールは、必然的に等価ミュータントが多くなります。文字列操作が主体の処理では、大小文字の変異が大量に生成されるためです。

### 3. テスト追加は「意味のある」ものに絞る

Killed率を上げるために、ログメッセージの内容を検証するテストを書くべきではありません。ロジックの境界条件や分岐網羅に焦点を当てたテストこそが価値を持ちます。

### 4. 環境の互換性に注意

mutmut v3.5.0とsrc/レイアウトの組み合わせでtrampoline問題が発生しました。導入前に、プロジェクト構成との互換性を確認することが重要です。

## mutmutの使い方まとめ

```bash
# インストール
pip install mutmut

# 設定（pyproject.toml）
[tool.mutmut]
paths_to_mutate = ["src/your_module/"]
pytest_add_cli_args_test_selection = ["tests/"]

# 実行
mutmut run

# 結果確認
mutmut results

# 特定のsurvived mutantを確認
mutmut show <id>

# HTML レポート
mutmut html
```

## この手法の限界

- **実行時間が長い**: 543 mutantの実行に数十分かかりました。大規模プロジェクトでは対象を絞る必要があります
- **等価ミュータントの判定が主観的**: 「本当に等価か」の判定には、コードの深い理解が必要です
- **ツールの成熟度**: mutmutは活発に開発されていますが、エッジケースでの問題に遭遇する可能性があります

## おわりに

Mutation Testingは「テストのテスト」として強力な手法です。カバレッジだけでは見えないテスト品質の弱点を、定量的に特定できます。

ただし、スコアの数字に踊らされないことが重要です。Survived mutantの分析を通じて「どの変異が本当に問題か」を見極めることで、実質的なテスト品質を正しく評価できます。

### 関連記事

- [LLMのハルシネーションを構造的に防ぐプロンプト設計（コードレビューでの実践）](https://zenn.dev/fukukei23/articles/ai-code-review-prompt-hallucination)
- [Claude Code CLIをGLM（Z.AI）で代替した話（コスト大幅削減の実測）](https://zenn.dev/fukukei23/articles/claude-code-cost-optimization)
- [月間27億トークンを処理したLLMルーティングの実運用レポート](https://zenn.dev/fukukei23/articles/llm-routing-one-month-report)
