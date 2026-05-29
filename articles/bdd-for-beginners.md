---
title: "BDD（振舞駆動開発）とは？TDDとの違いと使い方"
emoji: "🎭"
type: "tech"
topics: ["bdd", "tdd", "testing", "programming"]
published: true
---

## はじめに

TDD（テスト駆動開発）は聞いたことがあるけど、BDD（振舞駆動開発）はよくわからない。そんな方のために、BDDの基本を説明します。

## BDDとは？

BDDは**「システムの振る舞いを言葉で書く」**開発手法です。

### Given-When-Thenフォーマット

BDDでは、まるで小説を書くようにテストシナリオを記述します：

```
Given（前提）:  予約が1件ある状態で
When（操作）:  キャンセルを実行したら
Then（結果）:  ステータスが「cancelled」になる
```

- **Given**: テストを始める前の状態
- **When**: ユーザーが行う操作
- **Then**: 期待される結果

## TDDとのちがい

| 観点 | TDD | BDD |
|---|---|---|
| **テスト単位** | 関数・メソッド | ユーザー操作 |
| **視点** | 実装者の視点 | ユーザーの視点 |
| **テスト名** | `test_calculate_total()` | `test_確認済み予約をキャンセルすると_cancelled_になる` |

BDDはTDDの**上位互換**的位置づけ。実装詳細ではなく、「ユーザーが何をするか」に焦点を当てます。

## いつ使うか？

| 使うべき | 使うべきでない |
|---|---|
| ✅ ユーザー操作があるアプリ（Web、API） | ❌ データ変換・計算処理（TDDで十分） |
| ✅ 要件を「〜の場合、〜する」形式で整理したい | ❌ 使い捨てスクリプト |
| ✅ DDDのユースケースをテストしたい | |

## Pythonでの例

```python
# tests/test_reservation_bdd.py
import pytest
from domain.entities import Reservation, ReservationStatus, GuestCount

class TestReservationCancellation:
    """予約キャンセルの振舞い"""

    def test_確認済み予約をキャンセルすると_cancelled_になる(self):
        # Given: 確認済みの予約がある
        reservation = Reservation(
            id="R001",
            guest_name="田中",
            party_size=GuestCount(4),
            date="2026-06-01",
            status=ReservationStatus.CONFIRMED,
        )

        # When: キャンセルする
        reservation.cancel()

        # Then: ステータスが cancelled になる
        assert reservation.status == ReservationStatus.CANCELLED

    def test_未確認の予約はキャンセルできない(self):
        # Given: 未確認（PENDING）の予約
        reservation = Reservation(
            id="R002",
            guest_name="佐藤",
            party_size=GuestCount(2),
            date="2026-06-02",
            status=ReservationStatus.PENDING,
        )

        # When + Then: キャンセルしようとするとエラー
        with pytest.raises(ValueError, match="Confirmedのみ"):
            reservation.cancel()
```

## TypeScriptでの例

```typescript
// tests/reservation.behavior.test.ts
import { describe, it, expect } from "vitest";
import { Reservation, ReservationStatus } from "../src/domain/entities";

describe("予約キャンセルの振舞い", () => {
  it("確認済み予約をキャンセルすると cancelled になる", () => {
    // Given
    const reservation = new Reservation({
      id: "R001",
      guestName: "田中",
      partySize: new GuestCount(4),
      date: "2026-06-01",
      status: ReservationStatus.Confirmed,
    });

    // When
    reservation.cancel();

    // Then
    expect(reservation.status).toBe(ReservationStatus.Cancelled);
  });

  it("未確認の予約はキャンセルできない", () => {
    // Given
    const reservation = new Reservation({
      id: "R002",
      guestName: "佐藤",
      partySize: new GuestCount(2),
      date: "2026-06-02",
      status: ReservationStatus.Pending,
    });

    // When + Then
    expect(() => reservation.cancel()).toThrow();
  });
});
```

## BDDと他の手法の組み合わせ

BDDは以下の手法と組み合わせると効果的です：

- **DDD**: ドメインモデルのユースケースをGiven-When-Thenで表現
- **クリーンアーキテクチャ**: UseCase層のテストにBDDが最適
- **TDD**: BDDはTDDの上位互換。振舞いテストはBDD、単体テストはTDD

## まとめ

BDDは「ユーザーがシステムをどう使うか」をGiven-When-Thenの形式で記述し、それをそのままテストとして実行する手法です。

| ポイント | 内容 |
|---|---|
| **視点** | 実装者ではなくユーザーの視点 |
| **形式** | Given-When-Then |
| **テスト名** | 日本語で状況を記述（「〜的情况下，〜する」） |

TDDが「関数レベル」のテストなら、BDDは「システムレベル」のテスト。两者を使い分けることで、より保守性の高いコードになります。
