---
title: "【Python】SSRF・IDOR・Path Injectionを初心者向けに徹底解説：atelier-kyo-managerの実例から学ぶWebセキュリティ"
emoji: "🔒"
type: "tech"
topics: ["セキュリティ", "Python", "初心者向け", "ssrf", "idor"]
published: false
---

# はじめに

スクレイピングや自動化ツールを開発していると、「機能を正しく動かすこと」に目が行きがちです。しかし、外部からデータを取得したり、パラメータを元にURLを構築したりするシステムには、知らず知らずのうちに**重大なセキュリティ脆弱性**が潜んでいることがあります。

筆者は現在、SSENSEやBUYMAなどのECサイトを横断して価格監視を行うスクレイピングアプリ「**atelier-kyo-manager**」を開発しています。このプロジェクトで最近、`fix: セキュリティ修正 — SSRF対策 + IDOR対策 + ログインジェクション対策` というコミットを行いました。

この記事では、実際の開発現場で起きた3つの脆弱性（**SSRF**・**IDOR**・**Path Injection**）について、初心者の方にもわかりやすい具体例を交えて解説し、Pythonでどのように修正したのかをコードとともに紹介します。

# 1. SSRF（Server-Side Request Forgery）とは？

SSRF（サーバーサイド・リクエスト・フォージェリ）は、攻撃者が標的のサーバーに「意図しないURLへリクエストを送らせる」攻撃です。

スクレイピングアプリでは、ユーザー入力や設定ファイルの値をもとにして、動的にURLを生成してHTTPリクエストを送信することがよくあります。もし、リクエスト先のURLを全くチェックしていない場合、攻撃者に内部ネットワークの情報（AWSのメタデータなど）を窃取されたり、踏み台にされたりする危険があります。

## allowlist（許可リスト）による対策

SSRFの根本的な対策は、**「アクセスを許可するドメイン（URL）をあらかじめ決めておき、それ以外は一切リクエストを送らない」**というallowlist方式を採用することです。

atelier-kyo-managerでは、SSENSEやBUYMAなど、スクレイピング対象として許可したドメインのみにアクセスを制限するようにしました。

```python
from urllib.parse import urlparse

# 許可するドメインのリスト（allowlist）
ALLOWED_DOMAINS = {"ssense.com", "buyma.com", "ebay.com"}

def is_url_safe(url: str) -> bool:
    """URLが安全なドメインかチェックする関数"""
    try:
        parsed_url = urlparse(url)
        # netloc（ネットワーク上の位置＝ドメイン）を取得
        domain = parsed_url.netloc.lower()
        
        # www. などのサブドメインを考慮して末尾一致でチェック
        for allowed in ALLOWED_DOMAINS:
            if domain == allowed or domain.endswith(f".{allowed}"):
                return True
        return False
    except Exception:
        return False

def fetch_page(url: str):
    """安全なURLのみをスクレイピングする関数"""
    if not is_url_safe(url):
        raise ValueError(f"許可されていないドメインへのアクセスです: {url}")
    
    # ここで requests や httpx を使ってフェッチ処理を行う
    print(f"{url} へのアクセスを許可しました。")
```

このように「ブラックリスト（悪いものを弾く）」ではなく「ホワイトリスト（良いもの以外全部弾く）」を設けることで、強力にSSRFを防ぐことができます。

# 2. IDOR（Insecure Direct Object Reference）とは？

IDOR（安全でない直接オブジェクト参照）は、システムが認証や認可のチェックをせずに、ユーザーから指定されたID（オブジェクト）をそのまま使ってデータベース等のデータにアクセスしてしまう脆弱性です。

例えば、URLパラメータの `?user_id=1001` を `?user_id=1002` に書き換えるだけで、他人の個人情報が見えてしまうようなケースがこれに該当します。

スクレイピングのパイプラインでも同様の問題が起きます。例えば、商品ID `1001` に価格監視のタスクを設定した際、その商品が削除されていたり、URLが存在しなかったりするケースです。存在しないIDの参照に対するエラーハンドリングを怠ると、システム全体のデータ不整合（推測データでの利益計算など）を引き起こします。

## 存在確認（404チェック）による対策

atelier-kyo-managerでは、商品ID（URL）をフェッチした際に、ステータスコードを厳密にチェックし、リソースが存在しない（404 Not Found）場合は推測による計算処理をストップする修正を行いました。

```python
import httpx

def verify_product_integrity(product_url: str) -> dict:
    """商品ページの存在確認とデータ整合性チェック"""
    response = httpx.get(product_url, timeout=10.0)
    
    # IDOR対策: リソースの存在確認（404判定）
    if response.status_code == 404:
        raise ValueError("指定された商品ページが存在しません。URLを確認してください。")
    
    response.raise_for_status()
    
    # 正常な場合のみデータを返す（推測データでの処理を防止）
    return {"status": "ok", "data": response.text}
```

このように「データが本当に存在し、取得できているか」を確認するバリデーションを挟むことで、IDORに起因するエラーの波及を防ぐことができます。

# 3. Path Injection（パス・インジェクション）とは？

Path Injectionは、URLのパスやファイル名として使われるパラメータに、悪意のある文字列（`../` や `//` など）を注入する攻撃です。

例えば、ECサイトのカテゴリ名を引数に取る関数 `build_url("mens-shoes")` があったとします。もしここに `"../../malicious-path"` という文字列が渡された場合、生成されるURLが意図しないパスに解釈されてしまい、スクレイピングのルーティングが破壊されたり、内部のファイル構造を推測されたりするリスクがあります。

## 引数バリデーションの実装

この問題に対しては、引数として受け取る文字列の**フォーマットを厳密にバリデーション**するのが最も効果的です。最近のコミット `fix: category引数のバリデーション追加（URL Path Injection防止）` で対応したコードの概念は以下の通りです。

```python
import re

def build_category_url(category: str) -> str:
    """カテゴリ名から安全なURLを構築する関数"""
    # Path Injection対策: 半角英数字とハイフンのみを許可する
    # スラッシュやドットが含まれている場合はエラーとする
    pattern = re.compile(r"^[a-zA-Z0-9\-]+$")
    
    if not pattern.match(category):
        raise ValueError(f"無効なカテゴリ名です: {category}")
    
    return f"https://www.example.com/category/{category}"
```

正規表現を使って「スラッシュ（`/`）」や「ドット（`.`）」といった、パスを遡る可能性のある文字を弾くことで、安全にURLを構築できるようになります。

# おわりに

この記事では、実際のPythonスクレイピングアプリ（atelier-kyo-manager）の開発で行ったセキュリティ修正をもとに、以下の3つの脆弱性と対策を解説しました。

1. **SSRF対策**: ドメインの `allowlist` を作り、意図しないサーバーへのリクエストを防ぐ。
2. **IDOR対策**: レスポンスの `404ステータス` を確認し、存在しないデータへのアクセスをきちんと処理する。
3. **Path Injection対策**: 引数を `正規表現でバリデーション` し、不正なパスの注入を防ぐ。

どれもコード数行で追加できるシンプルな対策ですが、これらを入れるだけでシステムの堅牢性は劇的に上がります。機能を開発した後の「テストカバレッジ向上」も重要ですが、それ以前に「安全な入力を受け付けているか」を確認することは、実務において非常に重要です。

これから自動化ツールやスクレイピングシステムを作る方は、ぜひ今回の内容を設計段階から見直してみてください。少しの意識づけで、安全で信頼性の高いWebセキュリティを実現できるはずです。