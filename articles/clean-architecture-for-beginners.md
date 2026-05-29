---
title: "クリーンアーキテクチャ入門 — レイヤー分離で保守性の高い設計を"
emoji: "🧱"
type: "tech"
topics: ["cleanarchitecture", "ddd", "design", "programming"]
published: true
---

## クリーンアーキテクチャとは？

クリーンアーキテクチャは、**ビジネスロジックを外部依存から隔離し、依存関係を一方向に制限する**設計手法です。

###  핵심アイデア

「外部の世界（DB、Webフレームワーク、API）は変わりやすい」

「この内部の世界（ビジネスルール）は変わりにくい」

であれば、**内側（ビジネスルール）を外側（インフラ）から守る**のが自然でしょう。

## 4層アーキテクチャ

```
┌─────────────────────────────────────┐
│ Framework/Driver層 — Web、DB、API   │ ← 外の世界（変わりやすい）
└──────────────┬──────────────────────┘
               ↓ 依存
┌──────────────┴──────────────────────┐
│ Interface Adapter層 — コントローラー│
└──────────────┬──────────────────────┘
               ↓ 依存
┌──────────────┴──────────────────────┐
│ Use Case層 — アプリケーションロジック│
└──────────────┬──────────────────────┘
               ↓ 依存
┌──────────────┴──────────────────────┐
│ Domain層 — ビジネスルール          │ ← 内の世界（変わりにくい）
└─────────────────────────────────────┘
```

**ルール**: 内側の層は外側の層を知らない。依存は外→内の方向のみ。

## ディレクトリ構成

```
src/
  domain/        # エンティティ・ポート（外部依存ゼロ）
  usecases/      # ユースケース（ドメインのみに依存）
  adapters/      # DB・APIの実装（ポートを実装）
  frameworks/    # Webルーティング・DI設定
```

## 重要な概念：Port と Adapter

### Port（インターフェース）

「ドメインが欲しいもの」を定義します。

```python
# domain/ports.py
from typing import Protocol

class ReservationRepository(Protocol):
    """データを保存する能力を定義"""
    def save(self, reservation) -> str: ...
    def find_by_date(self, date: str) -> list: ...

class NotificationSender(Protocol):
    """メールを送る能力を定義"""
    def send_confirmation(self, email: str, reservation_id: str) -> None: ...
```

### Adapter（実装）

外部システム（SQLite、SendGrid等）がPortを実装します。

```python
# adapters/sqlite_repository.py
import sqlite3
from domain.entities import Reservation
from domain.ports import ReservationRepository

class SqliteReservationRepository(ReservationRepository):
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)

    def save(self, reservation: Reservation) -> str:
        # SQLで保存
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO reservations (guest_name, party_size, date) VALUES (?, ?, ?)",
            (reservation.guest_name, reservation.party_size, reservation.date)
        )
        self.conn.commit()
        return str(cursor.lastrowid)
```

## Pythonでの実装例

### Domain層

```python
# domain/entities.py
from dataclasses import dataclass

@dataclass
class Reservation:
    id: str
    guest_name: str
    party_size: int
    date: str

    def is_valid(self) -> bool:
        return self.party_size > 0 and len(self.guest_name) > 0
```

### UseCase層

```python
# usecases/create_reservation.py
class CreateReservationUseCase:
    def __init__(
        self,
        repo: ReservationRepository,    # インターフェース経由で注入
        notifier: NotificationSender,    # インターフェース経由で注入
    ):
        self.repo = repo
        self.notifier = notifier

    def execute(self, guest_name: str, party_size: int, date: str) -> str:
        reservation = Reservation(
            id="",
            guest_name=guest_name,
            party_size=party_size,
            date=date,
        )

        if not reservation.is_valid():
            raise ValueError("Invalid reservation")

        # Repositoryはinterfaceなので自由に切り替え可能
        reservation_id = self.repo.save(reservation)
        self.notifier.send_confirmation(guest_name, reservation_id)
        return reservation_id
```

## クリーンアーキテクチャ好处

| 好处 | 説明 |
|---|---|
| **テストしやすい** | Domain・UseCase層は外部依存がないので単体テストが簡単 |
| **変更に強い** | DBをSQLite→PostgreSQLに変えても、Domain層は変更不要 |
| **再利用しやすい** | Web APIでもCLIでも同じUseCaseが使える |

## まとめ

クリーンアーキテクチャ的核心は**「内側を外側から守る」**こと。

| ポイント | 内容 |
|---|---|
| **4層** | Domain → UseCase → Adapter → Framework |
| **依存方向** | 外→内のみ（内から外への依存は禁止） |
| **Port/Adapter** | 外部依存はinterfaceで抽象化 |

小さなアプリでは過度な設計かもしれませんが、業務ロジックが复杂になってきた段階で取り入れてみるのがおすすめです。
