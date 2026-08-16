---
title: "【Python】Open Redirect対策入門：CWE-601をFastAPIで実装する具体例"
emoji: "🔐"
type: "tech"
topics: ["Python", "Security", "FastAPI", "OpenRedirect", "CWE"]
published: false
---

## はじめに

個人で開発している管理アプリのセキュリティ見直しをしていたところ、ログイン後のリダイレクト処理に **Open Redirect（CWE-601）** の脆弱性があることに気づきました。この記事では、その実例を題材に、FastAPIでの具体的な修正方法とテストコードを初心者向けに解説します。

「リダイレクト先をURLパラメータで渡す」実装は一見便利ですが、検証なしに使うとフィッシング攻撃の踏み台になります。実際のコードを見ながら学んでいきましょう。

## 1. Open Redirectはなぜ危険なのか

多くのWebアプリには「ログイン前に見ていたページへ戻る」機能があります。FastAPIでは次のようなコードになりがちです。

```python
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()

@router.get("/login")
async def login(next: str = "/"):
    # ...認証処理...
    return RedirectResponse(url=next, status_code=303)
```

一見問題なさそうに見えますが、`next` はユーザーが自由に書き換えられるURLパラメータです。攻撃者は

```
https://myapp.example.com/login?next=https://evil.example.com/fake-login
```

のようなURLを用意して、SNSやメールでばら撒きます。被害者がログインすると、気づかないうちに偽のログインページへ飛ばされ、パスワードを盗まれる——これがOpen Redirect（CWE-601）です。

厄介なのは、**リンクの前半が正規のアプリドメイン**であるため、被害者が不審に思いにくい点です。私自身も「認証さえ通ればリダイレクト先は信頼できる」と思い込んでおり、コードレビューで初めて問題に気づきました。

## 2. 対策：origin検証と許可リスト

修正方針はシンプルで、**リダイレクト先が「自分のアプリ内」であることを機械的に検証してから飛ばす**ことです。標準ライブラリの `urlparse` と許可リスト（allowlist）で実装しました。

```python
from urllib.parse import urlparse

ALLOWED_HOSTS = {"myapp.example.com"}  # 自分のアプリのホスト名のみ

def is_safe_redirect(target: str) -> bool:
    """リダイレクト先として安全かどうかを判定する"""
    if not target:
        return False

    parsed = urlparse(target)

    # 相対パス（schemeもhostも無い）は自アプリ内への遷移なのでOK
    # ただし //host や \host は別ホスト扱いになるため除外
    if not parsed.scheme and not parsed.netloc:
        return not target.startswith(("//", "\\"))

    # 絶対URLは、許可リストに登録したホストのみ許可
    return (
        parsed.scheme in ("http", "https")
        and parsed.netloc in ALLOWED_HOSTS
    )

def safe_redirect(target: str) -> RedirectResponse:
    url = target if is_safe_redirect(target) else "/"
    return RedirectResponse(url=url, status_code=303)
```

エンドポイント側は `return safe_redirect(next)` に置き換えるだけです。実装のポイントは3つです。

- **相対パスのみ許可する方式が最も安全**です。アプリ内遷移しかないなら、絶対URLを一切受け付けない設計にするのがシンプルです
- 外部ドメインへ飛ばす正当なユースケースがある場合のみ、**許可リストでホストを限定**します
- `//evil.example.com` のような**スキーム相対URL**は `https://evil.example.com` と等価なので、除外を忘れないようにします

## 3. テスト：攻撃パターンをパラメータ化して網羅する

対策コードを書いただけで終わらせず、「攻撃パターンを弾けること」をテストで固定化しました。`pytest.mark.parametrize` を使うと、正常系と攻撃パターンを1つのテスト関数で網羅できます。

```python
import pytest
from app.security import is_safe_redirect

@pytest.mark.parametrize("target, expected", [
    # 正常系：許可されるべき値
    ("/dashboard", True),
    ("https://myapp.example.com/settings", True),
    # 攻撃パターン：すべて拒否されるべき値
    ("https://evil.example.com", False),   # 外部ドメインへの絶対URL
    ("//evil.example.com", False),         # スキーム相対URL
    ("\\\\evil.example.com", False),       # バックスラッシュ始まり
    ("javascript:alert(1)", False),        # 危険なスキーム
    ("", False),                           # 空文字
])
def test_is_safe_redirect(target: str, expected: bool) -> None:
    assert is_safe_redirect(target) is expected
```

さらにエンドポイントの結合テストとして、「悪意ある `next` を渡した際に `Location` ヘッダーが必ず安全なパスへ置き換わること」も確認しておくと安心です。

```python
def test_login_open_redirect_blocked(client) -> None:
    resp = client.get(
        "/login",
        params={"next": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/"
```

実際の修正では、このテスト群をパスさせてから、修正内容と経緯を変更履歴ドキュメントに記録するところまでを1つのIssueとして完結させました。セキュリティ修正は「直して終わり」ではなく、**再発防止のテストと記録を残して初めて完了**だと考えています。

## おわりに

Open Redirectは「リダイレクト先URLも外部からの入力である」という一点に気づけるかどうかの脆弱性でした。まとめると次の3つです。

1. `RedirectResponse` に渡す値を検証なしに使わない
2. 相対パスのみ許可、または許可リストでホストを限定する
3. 攻撃パターンを含むテストを書いて対策を固定化する

FastAPIに限らず、リダイレクト処理を書く機会はどんなフレームワークでもあります。この記事が同じ落とし穴を避ける助けになれば幸いです。