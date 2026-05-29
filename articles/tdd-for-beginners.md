---
title: "TDD（テスト駆動開発）を初めて学ぶ人のための完全ガイド"
emoji: "🧪"
type: "tech"
topics: ["tdd", "testing", "python", "typescript", "programming"]
published: true
---

## はじめに

「テスト駆動開発（TDD）」という言葉を聞いたことがあるけど、実際のやり方がよくわからない。そんな方のために、基本から丁寧に説明します。

## TDDとは？

TDDは**「テストを先に書き、そのテストが通るように実装する」**開発手法です。

### 3ステップサイクル

```
赤 → 緑 → リファクタリング
```

| ステップ | やること | 状態 |
|---|---|---|
| **赤** | まずテストを書く（まだ実装がないので失敗する） | ❌ 失敗 |
| **緑** | テストが通る最小のコードを書く | ✅ 成功 |
| **リファクタリング** | コードを整理する（テストが通ることを確認しながら） | ✅ 成功 |

このサイクルを**数分単位**で高速に回すのがポイントです。

## なぜTDDするのか？

### 1. 設計が自然と良くなる
「テストを書く」という行為が你先，意味着你先从"这个函数应该如何工作"的角度来思考，因此自然会产生更好的设计。

### 2. バグを早期発見できる
実装してからバグに気づくと、修正コストが高い。TDDなら常にテストが動作保証になっています。

### 3. リファクタリングが怖くなくなる
「あのコードを変更したいけど、今動いているものが壊れないか不安……」という担心がなくなります。

## Pythonでの例

```python
# tests/test_price_calculator.py

# --- サイクル1: 赤 ---
def test_calculate_tax_included_price():
    """税込み価格を計算する"""
    result = calculate_tax_included_price(1000, tax_rate=0.1)
    assert result == 1100

# --- サイクル1: 緑 ---
# price_calculator.py
def calculate_tax_included_price(base_price: float, tax_rate: float) -> float:
    return base_price * (1 + tax_rate)

# --- サイクル2: 赤（新しいテスト）---
def test_zero_price():
    """価格が0の場合は0を返す"""
    result = calculate_tax_included_price(0, tax_rate=0.1)
    assert result == 0

# --- サイクル2: 緑（0対応）---
# price_calculator.py
def calculate_tax_included_price(base_price: float, tax_rate: float) -> float:
    return base_price * (1 + tax_rate)  # 0 * 1.1 = 0 なのでOK

# --- サイクル3: 赤 ---
def test_negative_price_raises():
    """負の価格はエラー"""
    import pytest
    with pytest.raises(ValueError):
        calculate_tax_included_price(-100, tax_rate=0.1)
```

## TypeScriptでの例

```typescript
// src/priceCalculator.test.ts
import { describe, it, expect } from "vitest";
import { calculateTaxIncludedPrice } from "./priceCalculator";

describe("calculateTaxIncludedPrice", () => {
  it("税込み価格を計算する", () => {
    expect(calculateTaxIncludedPrice(1000, 0.1)).toBe(1100);
  });

  it("価格が0の場合は0を返す", () => {
    expect(calculateTaxIncludedPrice(0, 0.1)).toBe(0);
  });

  it("負の価格はエラー", () => {
    expect(() => calculateTaxIncludedPrice(-100, 0.1)).toThrow();
  });
});
```

```typescript
// src/priceCalculator.ts
export function calculateTaxIncludedPrice(
  basePrice: number,
  taxRate: number
): number {
  if (basePrice < 0) throw new Error("Price must be non-negative");
  return basePrice * (1 + taxRate);
}
```

## よくある疑問

### Q: 「何をテストすればいいかわからない」
A: **1つだけ**考えてください。「この関数にAを渡したら、Bが返るはず」。それだけで十分です。

### Q: 「テストが多すぎて書くのが苦痛」
A: それは設計が悪いサインかもしれません。関数を小さく分けて、1つのことだけさせましょう。

### Q: 「プライベートメソッドはテストしなくていいの？」
A: 原則的には**不要**です。プライベートメソッドは公開API経由で確認できます。

## まとめ

TDDは以下のサイクルで回します：

1. **赤**: テストを書く（失敗する）
2. **緑**: テストが通る最小コードを書く
3. **リファクタリング**: 整理する

大切なのは**数分単位で高速にサイクルを回すこと**です。完璧な設計を最初から求めず、小さく始めて徐々に改善していきましょう。
