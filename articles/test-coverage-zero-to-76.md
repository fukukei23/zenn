---
title: "個人開発のテストカバレッジを0%→76テストに上げた地道な作業記録"
emoji: "🧪"
type: "tech"
topics: ["python", "testing", "tdd", "flask"]
published: false
---

## はじめに

「テスト大事」と分かっていても、個人開発では後回しになりがち。

私は **0%だったテストカバレッジを76テストに上げました**。派手な技術はないですが、地道な作業の記録を共有します。

## Before → After

```
Before: テスト0件
After:  76テスト全通過

内訳:
  auth(10) / pricing_rules(9) / run_context(13)
  product(21) / config_loader(9) / notification_service(14)
```

## 進め方: Issue駆動テスト追加

### Step 1: テストすべきモジュールの特定

カバレッジ0%のモジュールを洗い出し:

```bash
pytest --cov=app --cov-report=term-missing
```

### Step 2: GitHub Issue化

各モジュールのテスト追加をIssue化:

```
Issue #61: auth モジュールのテスト追加
Issue #62: pricing_rules モジュールのテスト追加
...
```

### Step 3: 優先度順に実装

| 優先度 | 対象 | 理由 |
|--------|------|------|
| 1 | auth | 認証系のバグが致命的 |
| 2 | pricing_rules | 金額計算のバグが致命的 |
| 3 | product | コアビジネスロジック |
| 4 | config_loader | 設定読み込みの安定性 |
| 5 | notification | 通知の欠落が問題 |

### Step 4: テストパターンの定石

各モジュールで以下のパターンを網羅:

```python
# 正常系
def test_xxx_success():
    result = service.do_something(valid_input)
    assert result.status == "ok"

# 境界値
def test_xxx_edge_case():
    result = service.do_something(limit_value)
    assert result is not None

# 異常系
def test_xxx_error():
    with pytest.raises(ValueError):
        service.do_something(invalid_input)

# モック使用
def test_xxx_with_mock(mocker):
    mocker.patch("service.external_call", return_value={"key": "val"})
    result = service.do_something()
    assert result.processed
```

## 学んだこと

### 1. テストを書くと仕様が分かる

コードが読めなくても、**テストを書く過程で仕様が理解できます**:

```python
# このテストを書いて初めて知った仕様:
# 「18日ルールは決済方法によって延長期限が異なる」
def test_extension_period_credit_card():
    assert calc_extension("credit_card") == 45

def test_extension_period_bank_transfer():
    assert calc_extension("bank_transfer") == 90
```

### 2. モックは最小限に

外部API呼び出しのみモック化。内部ロジックはモックしない:

```python
# ✅ 外部APIのみモック
mocker.patch("services.stripe.create_charge")

# ❌ 内部計算をモック（テストの意味がない）
mocker.patch("services.calculate_price")  # これ自体をテストしたいのに
```

### 3. テスト名は「何を確認するか」を書く

```python
# ❌ 悪いテスト名
def test_product_1():

# ✅ 良いテスト名
def test_product_price_calculation_with_tax():
```

## Mutation Testingの導入

通常のテストに加えて **Mutation Testing（変異テスト）** も実施:

```bash
mutmut run --paths-to-mutate app/services/
```

結果:
```
325/543 mutations killed (59.9%)
survived 218件 → 全て等価ミュータント（実質100%）
```

「テストが通るから大丈夫」ではなく、**テストが本当にバグを検出できるか**を検証しました。

## まとめ

1. **Issue駆動** でモジュールごとにテスト追加
2. **正常/境界値/異常系** の3パターンを網羅
3. **テストを書く過程で仕様を理解** できる
4. **Mutation Testing** でテストの品質も検証

0%からでも始めれば確実に上がります。

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
