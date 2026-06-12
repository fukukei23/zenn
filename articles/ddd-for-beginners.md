---
title: "ドメイン駆動設計（DDD）を初めて学ぶ人のための実践ガイド"
emoji: "🏛️"
type: "tech"
topics: ["ddd", "cleanarchitecture", "domain", "programming"]
published: true
---

## はじめに

DDD（ドメイン駆動設計）は聞いたことがあるけど、「何から始めればいいのかわからない」という方は多いのではないでしょうか。

この入門ガイドでは、**複雑なビジネスロジックをコードで正確に表現する**ための基本概念と実践方法を説明します。

## 5つの重要な概念

### 1. ユビキタス言語

**開発者とビジネス側で同じ言葉を使う**原則です。

「予約」と「予定」は、業務上では異なる概念かもしれません。明確な区分がないと、コード上でも混乱が生じます。DDDではコード内の名前も業務用語に合わせます。

### 2. エンティティ

**同一性（ID）で識別されるオブジェクト**。

```python
# 例: 予約はIDで識別される
reservation1 = Reservation(id="R001", guest_name="田中", ...)
reservation2 = Reservation(id="R002", guest_name="田中", ...)

# IDが違うので別のオブジェクト
assert reservation1 != reservation2
```

### 3. 値オブジェクト

**属性だけで識別されるオブジェクト**。不変（immutable）。

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class GuestCount:
    value: int

    def __post_init__(self):
        if self.value < 1 or self.value > 20:
            raise ValueError(f"人数は1〜20人: {self.value}")
```

`GuestCount(4)`と`GuestCount(4)`は属性が同じなので等しいものとして扱います。

### 4. 集約（Aggregate）

**整合性を保つ単位**。外部からは集約ルート経由でのみアクセスします。

```
予約（集約ルート）← 予約アイテム ← 予約オプション
```

### 5. ドメインサービス

**単一エンティティに属さないビジネスルール**。

例：「重複予約のチェック」— 1つの予約エンティティだけでは判断できない。

## Pythonでの実装例

```python
from dataclasses import dataclass
from enum import Enum

# --- 値オブジェクト（不変）---
@dataclass(frozen=True)
class GuestCount:
    value: int

    def __post_init__(self):
        if self.value < 1 or self.value > 20:
            raise ValueError(f"人数は1〜20人: {self.value}")

# --- ステータス ---
class ReservationStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

# --- エンティティ ---
@dataclass
class Reservation:
    id: str
    guest_name: str
    party_size: GuestCount
    date: str
    status: ReservationStatus = ReservationStatus.PENDING

    def confirm(self) -> None:
        """予約を確定"""
        if self.status != ReservationStatus.PENDING:
            raise ValueError("確定できるのはPENDINGのみ")
        self.status = ReservationStatus.CONFIRMED

    def cancel(self) -> None:
        """予約をキャンセル"""
        if self.status != ReservationStatus.CONFIRMED:
            raise ValueError("キャンセルできるのはCONFIRMEDのみ")
        self.status = ReservationStatus.CANCELLED

# --- ドメインサービス ---
class ReservationDomainService:
    @staticmethod
    def check_double_booking(
        new_res: Reservation,
        existing: list[Reservation]
    ) -> bool:
        """同名・同日・未取消の予約がないかチェック"""
        same = [
            r for r in existing
            if r.date == new_res.date
            and r.guest_name == new_res.guest_name
            and r.status != ReservationStatus.CANCELLED
        ]
        return len(same) > 0
```

## いつDDDを使うべきか？

| DDD向き | DDD不要 |
|---|---|
| ✅ 予約システム、在庫管理、契約管理など業務ルールが複雑 | ❌ 単純なCRUDアプリ |
| ✅ ルールが頻繁に変わる（業務知識の変化に追従したい） | ❌ データの変換・加工中心 |
| ✅ ユーザーとの会話から要件を整理したい | ❌ 小規模スクリプト |

## クリーンアーキテクチャとの関係

DDDは**クリーンアーキテクチャのDomain層を充実させる手法**です。

```
Domain層（DDDで設計）→ UseCase層 → Adapter層 → Framework層
```

DDDで設計したドメインモデルを、クリーンアーキテクチャのレイヤー構造に配置します。

## まとめ

DDDの核心は**「ビジネスルールを正確にコードで表現する」**こと。

| 概念 | 役割 |
|---|---|
| ユビキタス言語 | 業務用語の統一 |
| エンティティ | IDで識別される業務オブジェクト |
| 値オブジェクト | 属性で識別される不変オブジェクト |
| 集約 | 整合性を保つ単位 |
| ドメインサービス | 複数エンティティにまたがるルール |

複雑な業務ロジックを持つシステムは、DDDの考え方を取り入れてみてください。
