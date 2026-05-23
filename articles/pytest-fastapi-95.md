---
title: "【pytest】FastAPIの例外ハンドラを95%カバレッジにする具体的な書き方"
emoji: "📝"
type: "tech"
topics: ["Python", "pytest", "FastAPI", "例外処理", "テストカバレッジ"]
published: false
---

```markdown
---
title: "【pytest】FastAPIの例外ハンドラを95%カバレッジにする具体的な書き方"
emoji: "🛡️"
type: "tech"
topics: ["Python", "pytest", "FastAPI", "例外処理", "テストカバレッジ"]
published: false
---

# はじめに

FastAPIでAPIサーバーを構築していると、**例外ハンドラ**（`exception_handler`）のテストカバレッジが上がらずに困った経験はありませんか？

通常のエンドポイントはテストしやすいのですが、例外ハンドラは「わざと例外を起こす」という一手間が必要なうえに、`detail` の型が `str` なのか `dict` なのかで分岐が変わっていたり、フォールバックパスが存在していたりと、意外と網羅が難しい領域です。

本記事では、実際のプロジェクト **NexusCore** の開発で `81.54% → 95%+` へカバレッジを向上させた経験をもとに、FastAPIの例外ハンドラを漏れなくテストする技法を具体的なコード付きで解説します。

:::message
この記事は、FastAPIとpytestの基本的な使い方を知っている方を対象としています。「FastAPIのテストを書いたことがある」くらいのレベルを想定しています。
:::

# 対象となる例外ハンドラのおさらい

まず、テスト対象となる典型的な例外ハンドラの実装を確認しましょう。NexusCoreでは `fastapi_app.py` に次のようなハンドラが定義されています。

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI()

# HTTPステータスコード → 内部エラーコード のマッピング
code_map = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    422: "VALIDATION_ERROR",
}

UNKNOWN_ERROR = "UNKNOWN_ERROR"


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # 分岐1: code_mapに存在するステータスコードか？
    error_code = code_map.get(exc.status_code, UNKNOWN_ERROR)

    # 分岐2: detailがdictかstrか？
    if isinstance(exc.detail, dict):
        detail = exc.detail
    else:
        detail = {"message": str(exc.detail)}

    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": error_code, "detail": detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        # 分岐3: field_pathの構築
        field_path = ".".join(str(loc) for loc in err.get("loc", []))
        errors.append({
            "field": field_path,
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        })

    return JSONResponse(
        status_code=422,
        content={"error_code": "VALIDATION_ERROR", "detail": {"errors": errors}},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # 分岐4: 捕捉されなかったすべての例外
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "detail": {"message": "Internal Server Error"}},
    )
```

一見シンプルですが、**4つの分岐**が存在しており、これらをすべて通過させるテストを書く必要があります。

# カバレッジを95%にする具体的なテスト戦略

ここからが本題です。各分岐を確実に通過させるテストを6つ書いていきましょう。

## テストの準備

テストクライアントには `httpx.AsyncClient` または `TestClient` を使います。NexusCoreでは `httpx.AsyncClient` + `asgi_lifespan` を採用していますが、ここでは分かりやすさを優先して `TestClient` で説明します。

```python
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# --- テスト用の最小アプリ ---
def create_test_app():
    app = FastAPI()

    # （先ほどと同じ例外ハンドラを登録）
    # ...

    # テスト用エンドポイント: 意図的に例外を起こす
    @app.get("/raise-http/{code}")
    async def raise_http(code: int, detail_type: str = "str"):
        if detail_type == "dict":
            raise HTTPException(status_code=code, detail={"key": "value"})
        raise HTTPException(status_code=code, detail="error occurred")

    @app.get("/raise-unhandled")
    async def raise_unhandled():
        raise RuntimeError("something went wrong")

    class Item(BaseModel):
        name: str
        age: int

    @app.post("/validate")
    async def validate_endpoint(item: Item):
        return item

    return app


@pytest.fixture
def client():
    app = create_test_app()
    return TestClient(app, raise_server_exceptions=False)
```

`raise_server_exceptions=False` にするのがポイントです。これを設定しないと、例外ハンドラがレスポンスを返す前に `TestClient` が例外を再送出してしまいます。

## テスト1: code_map fallback（文字列detail）

`code_map` に**存在しないステータスコード**を渡し、かつ `detail` が文字列の場合をテストします。このパスは `UNKNOWN_ERROR` フォールバックと文字列 `detail` の分岐を同時にカバーできます。

```python
def test_http_exception_code_map_fallback_str_detail(client):
    """code_mapにないステータスコード + detailが文字列 → UNKNOWN_ERROR"""
    response = client.get("/raise-http/503?detail_type=str")

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "UNKNOWN_ERROR"
    assert body["detail"]["message"] == "error occurred"
```

**なぜ503なのか？** `code_map` には400・401・403・404・422しか定義されていないため、503を渡すことで `code_map.get(503, UNKNOWN_ERROR)` が `UNKNOWN_ERROR` を返すフォールバックパスを通過できます。ここをテストしないと、`code_map` に新しいコードを追加したときにフォールバックが壊れていても気づけません。

## テスト2: code_mapに存在するコード（文字列detail）

次に、`code_map` に**存在する**ステータスコードの場合をテストします。

```python
def test_http_exception_code_map_hit_str_detail(client):
    """code_mapにあるステータスコード + detailが文字列"""
    response = client.get("/raise-http/404?detail_type=str")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "NOT_FOUND"
    assert body["detail"]["message"] == "error occurred"
```

## テスト3: dict detailの分岐

`detail` が `dict` の場合、そのまま `detail` フィールドに格納される分岐をテストします。

```python
def test_http_exception_dict_detail(client):
    """detailがdictの場合 → dictがそのまま格納される"""
    response = client.get("/raise-http/400?detail_type=dict")

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "BAD_REQUEST"
    assert body["detail"] == {"key": "value"}
    # dictの場合は "message" キーが存在しないことを確認
    assert "message" not in body["detail"]
```

`isinstance(exc.detail, dict)` の `True` 側を通すことで、`str` の場合と `dict` の場合でレスポンス構造が変わることを保証できます。

## テスト4: バリデーションエラー（field_path構築）

`RequestValidationError` のハンドラが正しくエラーを変換できているかをテストします。必須フィールドを欠いたリクエストを送ることで、`loc` タプルから `field_path` を構築する処理を検証します。

```python
def test_validation_error_with_field_path(client):
    """バリデーションエラー → field_path + エラー情報の変換"""
    response = client.post("/validate", json={"name": 123, "age": "not_int"})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    errors = body["detail"]["errors"]
    assert len(errors) >= 1
    # field_pathが "body.field_name" の形式であることを確認
    assert any("body" in e["field"] for e in errors)
    assert all("message" in e for e in errors)
    assert all("type" in e for e in errors)
```

Pydantic v2では `loc` が `(body, field_name)` のタプルになるため、`".".join(...)` で `"body.field_name"` という文字列に変換されるはずです。このテストでその変換が機能していることを確認します。

## テスト5: バリデーションエラー（locが空のエッジケース）

`loc` が空のエッジケースも考慮します。Pydanticのバリデーションでは通常 `loc` が空になることは稀ですが、サードパーティのバリデータを使う場合に発生する可能性があります。

```python
def test_validation_error_empty_loc(client):
    """locが空のバリデーションエラー → 空のfield_path"""
    # 直接RequestValidationErrorを投ぐエンドポイントを追加してテスト
    # （実装に応じてモック等で対応）
    pass
```

## テスト6: 捕捉されない例外（general exception handler）

最後に、どのハンドラにも捕捉されなかった例外が `general_exception_handler` に到達するパスをテストします。ここは**本番環境でユーザーにスタックトレースを露出しない**ことを保証する重要なテストです。

```python
def test_general_exception_handler(client):
    """捕捉されない例外 → 500 + INTERNAL_ERROR"""
    response = client.get("/raise-unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "Internal Server Error" in body["detail"]["message"]
    # スタックトレース情報が漏洩していないことを確認
    assert "RuntimeError" not in str(body)
```

# カバレッジ向上のポイントまとめ

NexusCoreの実際の開発で効果的だった工夫を3つにまとめます。

## 1. 「分岐ごと」ではなく「シナリオごと」に整理する

カバレッジの未カバー箇所を見ると、「この `if` ブランチが通っていない」という単位で表示されます。しかし、テストを書くときは**「どんな状況でこの分岐に到達するのか」というシナリオ**で整理する方が漏れにくいです。

| シナリオ | カバーされる分岐 |
|---|---|
| code_mapにないコード + str detail | `UNKNOWN_ERROR` フォールバック, `str` 分岐 |
| code_mapにあるコード + str detail | `code_map` ヒット, `str` 分岐 |
| code_mapにあるコード + dict detail | `code_map` ヒット, `dict` 分岐 |
| バリデーションエラー | `loc` → `field_path` 変換 |
| 捕捉されない例外 | `general_exception_handler` |

## 2. `raise_server_exceptions=False` を忘れない

`TestClient` のデフォルトでは、例外ハンドラがレスポンスを返す前に例外が再送出されます。テスト対象が例外ハンドラの場合は、このオプションが必須です。

```python
# ❌ 例外が再送出されてテストが失敗する
TestClient(app)

# ✅ 例外ハンドラのレスポンスを取得できる
TestClient(app, raise_server_exceptions=False)
```

## 3. 意図的に例外を起こすテスト用エンドポイントを用意する

実装のエンドポイント経由だと「特定のステータスコードの例外を起こす」のが難しい場合があります。テスト用アプリケーションにパラメータ化されたエンドポイントを用意することで、任意の例外シナリオを簡単に再現できます。

```python
@app.get("/raise-http/{code}")
async def raise_http(code: int, detail_type: str = "str"):
    if detail_type == "dict":
        raise HTTPException(status_code=code, detail={"key": "value"})
    raise HTTPException(status_code=code, detail="error occurred")
```

# おわりに

FastAPIの例外ハンドラは、一見すると「テストしなくても動くでしょ」と思われがちですが、**本番環境でエラー時のレスポンス構造が壊れると、クライアント側のエラーハンドリングまで影響を受ける**重要なコンポーネントです。

NexusCoreでは、今回紹介した6つのテストパターンを追加することで `81.54% → 95%+` へカバレッジを向上させ、**5472の既存テストすべてが通過する**ことも確認しました。テストを追加して既存が壊れる不安も、フルスイートを実行すればすぐに検知できます。

例外ハンドラのテストを後回しにしている方は、ぜひこの記事のパターンを参考に、1つずつテストを追加してみてください。

:::message
NexusCoreのPRでは、他にも認証（`auth.py`）のフォールバックパスやAPIキー管理（`api_keys.py`）のエラーパスなど、多数のカバレッジ向上を行っています。興味がある方は[リポジトリ](https://github.com/fukukei23/NexusCore)も覗いてみてください。
:::
```