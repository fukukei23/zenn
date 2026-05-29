---
title: "仕様駆動開発 — 「何を作るか」を先に決めて品質を保つ方法"
emoji: "📋"
type: "tech"
topics: ["openapi", "swagger", "pydantic", "zod", "programming"]
published: true
---

## 仕様駆動開発とは？

 традиционные软件开发では「仕様書を作成してから実装」， но на практике仕様書と実装がずれてしまうことが多かった。

仕様駆動開発では、**仕様を「実行可能な形」で管理する**ことで、この問題を解決します。

### 開発のフロー

```
1. 仕様を書く（OpenAPI、JSON Schema等）
2. 仕様を実行可能にする（モックサーバー、テストコード生成）
3. 仕様に基づいてテストを書く
4. テストが通るように実装する
```

## なんで仕様を先に書くのか？

| 好处 | 説明 |
|---|---|
| **思考の整理** | 実装前にデータの形を考えることで、不明な点を早期発見 |
| **ドキュメントと実装の整合性** | 仕様書とコードがズレなくなる |
| **チーム間の意思疎通** | 仕様書ベースで議論できる |

## OpenAPI（Swagger）でAPI仕様を書く

OpenAPIはAPIの仕様をYAMLまたはJSONで記述する標準フォーマットです。

```yaml
# specs/api.yaml
openapi: "3.0.0"
info:
  title: Reservation API
  version: "1.0"
paths:
  /reservations:
    post:
      summary: 予約を作成
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [guest_name, party_size, date]
              properties:
                guest_name:
                  type: string
                  minLength: 1
                party_size:
                  type: integer
                  minimum: 1
                  maximum: 20
                date:
                  type: string
                  format: date
      responses:
        "201":
          description: 作成成功
          content:
            application/json:
              schema:
                type: object
                properties:
                  id: { type: string }
                  status: { type: string, enum: [pending] }
        "400":
          description: バリデーションエラー
```

## Pydanticでデータモデルを定義（Python）

PydanticはPythonでデータのバリデーションを行うライブラリです。OpenAPIのschemaと自動的に対応します。

```python
from pydantic import BaseModel, Field
from datetime import date

class CreateReservationRequest(BaseModel):
    guest_name: str = Field(min_length=1)
    party_size: int = Field(ge=1, le=20)  # 1以上20以下
    date: date

class ReservationResponse(BaseModel):
    id: str
    status: str

# --- テスト（仕様に基づく）---
from fastapi.testclient import TestClient

def test_create_reservation_success(client: TestClient):
    response = client.post("/reservations", json={
        "guest_name": "田中",
        "party_size": 4,
        "date": "2026-06-01",
    })
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"

def test_create_reservation_invalid_party_size(client: TestClient):
    response = client.post("/reservations", json={
        "guest_name": "田中",
        "party_size": 0,  # 仕様: minimum: 1
        "date": "2026-06-01",
    })
    assert response.status_code == 400  # 仕様: 400エラー
```

## Zodでデータモデルを定義（TypeScript）

ZodはTypeScriptでスキーマファーストな開発を実現するライブラリです。

```typescript
// schemas/reservation.ts
import { z } from "zod";

export const CreateReservationSchema = z.object({
  guest_name: z.string().min(1),
  party_size: z.number().int().min(1).max(20),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
});

export type CreateReservationRequest = z.infer<typeof CreateReservationSchema>;

export const ReservationResponseSchema = z.object({
  id: z.string(),
  status: z.enum(["pending"]),
});

// --- テスト（スキーマに基づく）---
describe("CreateReservationSchema", () => {
  it("有効なリクエストを受け入れる", () => {
    const result = CreateReservationSchema.safeParse({
      guest_name: "田中",
      party_size: 4,
      date: "2026-06-01",
    });
    expect(result.success).toBe(true);
  });

  it("party_sizeが0ならエラー", () => {
    const result = CreateReservationSchema.safeParse({
      guest_name: "田中",
      party_size: 0,  // 仕様: minimum: 1
      date: "2026-06-01",
    });
    expect(result.success).toBe(false);
  });
});
```

## 仕様駆動 × CI/CD

仕様駆動開発の效力は、CI/CDと組み合わせると最大化されます。

```
仕様変更 → CI発動 → 自動テスト → 仕様の整合性を常時検証
```

## まとめ

| ポイント | 内容 |
|---|---|
| **先に仕様を書く** | 実装より先にAPI・データの形を決める |
| **実行可能な仕様** | OpenAPI、Pydantic、Zod等形式化されたものを使う |
| **仕様がSSOT** | 仕様と実装が矛盾したら仕様を正とする |

ウォーターフォール的に「仕様書作ってから実装」ではなく、アジャイル的に「仕様を小さく書きながら実装と検証を繰り返す」のが仕様駆動开发です。
