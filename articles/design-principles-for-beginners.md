---
title: " SOLID・DRY・KISS・YAGNI — 知ってると得する設計基本原则"
emoji: "📐"
type: "tech"
topics: ["design", "solid", "programming", "refactoring"]
published: true
---

## はじめに

「良いコード」と「悪いコード」の違いはどこにあるのでしょう？

その質問に答えてくれるのが、**設計原则**です。特定のプログラミング言語やフレームワークに依存しない、普遍的な設計の指針を学びましょう。

## 4つの基本設計原则

### DRY — Don't Repeat Yourself

**同じロジックを複数箇所に書かない。**

```python
# ❌ DRY違反: 同じ計算が2箇所にある
def calculate_order_price_v1(items):
    subtotal = sum(item["price"] * item["qty"] for item in items)
    tax = subtotal * 0.1
    return subtotal + tax

def calculate_order_price_v2(items):
    subtotal = sum(item["price"] * item["qty"] for item in items)
    tax = subtotal * 0.1  # 同じ計算の重複
    return subtotal + tax + discount

# ✅ DRY遵守: 共通ロジックを関数に
def calculate_subtotal(items):
    return sum(item["price"] * item["qty"] for item in items)

def calculate_order_price(items):
    subtotal = calculate_subtotal(items)
    tax = subtotal * 0.1
    return subtotal + tax
```

### KISS — Keep It Simple, Stupid

**複雑な解決策より、シンプルな方を選ぶ。**

```python
# ❌ KISS違反: 理解しづらい複雑なコード
def process(x):
    return list(filter(lambda y: y > 0, map(lambda y: y * 2, x)))

# ✅ KISS遵守: 誰の目から見ても分かるコード
def double_positive_numbers(numbers):
    result = []
    for num in numbers:
        if num > 0:
            result.append(num * 2)
    return result
```

### YAGNI — You Aren't Gonna Need It

**今必要ない機能は、先回りして作らない。**

```python
# ❌ YAGNI違反: 後で必要になるかもしれない機能を先に作る
class User:
    name: str
    email: str
    phone: str           # 今のところ不要
    fax_number: str       # 絶対に使わない
    telex: str            # 1980年代か？

# ✅ YAGNI遵守: 今本当に必要なものだけ
class User:
    name: str
    email: str
```

### SoC — Separation of Concerns

**関心事を分離する。**

```python
# ❌ SoC違反: 1つの関数に複数の関心事
def process_order(order):
    total = calculate_total(order["items"])    # 計算
    send_email(order["email"], total)          # メール送信
    update_inventory(order["items"])           # 在庫更新
    log_transaction(order, total)              # ロギング

# ✅ SoC遵守: 関心事ごとに分離
def calculate_order(order):
    return calculate_total(order["items"])

def execute_order(order):
    email = send_confirmation_email(order)
    update_inventory(order["items"])
    log_transaction(order)
```

## SOLID 5原則

### SRP — Single Responsibility（単一責任の原則）

**1つのクラス・関数は1つの責務だけを持つ。**

```python
# ❌ SRP違反: ユーザーの管理与ビジネスロジックが混在
class UserManager:
    def create_user(self, name, email):
        # ユーザー作成
        ...
        self.send_welcome_email(email)  # メール送信用のコードも混在

    def send_welcome_email(self, email):
        # メール送信
        ...

# ✅ SRP遵守: 責務ごとに分離
class UserService:
    def create_user(self, name, email):
        # ユーザー作成のみ
        return User(name, email)

class EmailService:
    def send_welcome_email(self, email):
        # メール送信のみ
        ...
```

### DIP — Dependency Inversion（依存関係逆転の原則）

**上位モジュール（ビジネスロジック）は下位モジュール（外部API等）に依存しない。インターフェースを間に挟む。**

```python
# ❌ DIP違反: ビジネスロジックが外部サービスに直接依存
class OrderService:
    def confirm(self, order):
        stripe = StripeClient(api_key="...")  # 具体的な実装に依存
        stripe.charge(order.total)

# ✅ DIP遵守: インターフェースを挟む
class PaymentGateway(Protocol):
    def charge(self, amount: int) -> None: ...

class OrderService:
    def __init__(self, payment: PaymentGateway):
        self.payment = payment

    def confirm(self, order):
        self.payment.charge(order.total)
```

## まとめ：設計原则活かし方

| 原則 | 活かすべき場面 |
|---|---|
| DRY | 同じコードを2回以上書きたくなったら |
| KISS | コードが複雑になったら |
| YAGNI | 「後で必要になるかも」と思った時 |
| SoC | 1つの関数が大きくなったら |
| SRP | クラスを変更する理由が複数ありえたら |
| DIP | 外部依存がビジネスロジックに漏れていたら |

大切なのは、**机械的に適用するのではなく、理解した上で活かす**ことです。経験が积むとともに、自然とこれらの原則が意識できるようになるでしょう。
