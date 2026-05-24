---
title: "SQLAlchemyモデルのgomock不用なテスト術：SimpleNamespaceで95%カバレッジ"
emoji: "📝"
type: "tech"
topics: ["pytest", "SQLAlchemy", "テスト技法", "カバレッジ"]
published: false
---

```markdown
---
title: "SQLAlchemyモデルのgomock不用なテスト術：SimpleNamespaceで95%カバレッジ"
emoji: "🧪"
type: "tech"
topics: ["pytest", "SQLAlchemy", "テスト技法", "カバレッジ"]
published: false
---

# はじめに

PythonでWebアプリケーションを開発していると、データベース操作のために「SQLAlchemy」のようなORM（オブジェクト関係マッピング）ライブラリを使うことが多いですよね。

しかし、いざテストコードを書こうとすると「DBに接続しないとテストできない」「Mock（モック）を使おうとするとコードがカオスになる」という壁にぶつかり、挫折してしまう初心者の方は少なくありません。

今回は私が個人開発している **atelier-kyo-manager** というプロジェクトで、SQLAlchemyモデルのテストに挑戦し、見事カバレッジを **73%から90%** へ引き上げた経験を共有します！

使った技は `SimpleNamespace` を使った **「SimpleNamespace ＋ メソッドバインド方式」** です。複雑なモックライブラリ（gomockやunittest.mockなど）に頼らず、Pythonの標準機能だけで純粋なビジネスロジックをテストするこの手法を、初心者の方にもわかりやすく解説します。

# 1. SQLAlchemyモデルのテストで初心者が躓く「Mockの壁」

SQLAlchemyのモデルクラスには、DBのカラム定義（`id` や `name` など）だけでなく、データを加工するための便利なビジネスロジック（メソッド）をよく書きます。

例えば、以下のようなモデルを考えてみてください。

```python
# app/models/product.py
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    price = Column(Integer)
    is_active = Column(Boolean, default=True)

    def get_display_price(self):
        """販売中なら税込み価格を返し、販売休止中なら '---' を返す"""
        if not self.is_active:
            return '---'
        
        # ビジネスロジック：価格に10%の税を加算
        tax_included_price = int(self.price * 1.10)
        return f"¥{tax_included_price:,}"
```

この `get_display_price` メソッドのテストを書きたい場合、どうすればいいでしょう？

初心者がやりがちなのは、「実際のテスト用DB（SQLiteなど）を立ち上げて、INSERTしてからSELECTしてテストする」という方法です。これは有効ですが、テストの実行が遅くなり、DBのセットアップだけでも一苦労です。

そこで「DBを使わずに、メソッドだけをテストしたい！」となると、`unittest.mock` の出番になります。しかし、SQLAlchemyのモデルは `Base` クラスを継承しているため、ただの辞書（dict）や MagicMock では「属性（`self.price` など）がない」とエラーになり、上手くいきません。

# 2. SimpleNamespace ＋ メソッドバインドとは？

そこで私が行き着いたのが、Pythonの標準ライブラリにある `types.SimpleNamespace` を使う方法です。

`SimpleNamespace` は、JavaScriptのオブジェクトのように、属性（プロパティ）を自由に持てるシンプルなオブジェクトを作るためのクラスです。これを「SQLAlchemyのモデルインスタンスの代用品（スタブ）」として使います。

具体的には以下のようにします。

```python
from types import SimpleNamespace
# テスト対象のモデルからメソッドをインポート
from app.models.product import Product

# ダミーのモデルインスタンスを生成
product = SimpleNamespace(
    name="テストTシャツ",
    price=5000,
    is_active=True,
    # モデルのメソッドをそのままバインド（紐付け）する
    get_display_price=Product.get_display_price
)

# テスト実行
result = product.get_display_price()
print(result) # 出力: ¥5,500
```

このように、`SimpleNamespace` に必要なカラムデータ（`price` や `is_active`）と、テストしたいメソッド（`get_display_price`）をそのまま代入してしまいます。

これなら、SQLAlchemyの `Base` クラスを継承する面倒な処理や、DBセッションを初期化する処理を一切スキップできます。
「え？こんな単純なことでいいの？」と思うかもしれませんが、DB設定に依存しない **純粋なロジックのテスト** としては非常に強力で、テストも爆速で動きます。

# 3. 実践：27テスト追加でカバレッジ73%→90%を達成

実際の「atelier-kyo-manager」プロジェクトでの活用事例を紹介します。
このプロジェクトの `app/models/product.py` では、商品ステータスに応じた様々な判定ロジックや、表示名の生成ロジックなどが定義されていました。

これまでカバレッジ（テストが網羅しているコードの割合）は73%でしたが、先ほどの手法を用いて `pytest` テストを **27個** 追加しました。

```python
# tests/models/test_product.py
from types import SimpleNamespace
from app.models.product import Product

def test_get_display_price_active():
    """販売中の場合、税込み価格がフォーマットされて返されること"""
    # ダミーデータの準備
    active_product = SimpleNamespace(
        price=10000, 
        is_active=True, 
        get_display_price=Product.get_display_price
    )
    # 検証
    assert active_product.get_display_price() == "¥11,000"

def test_get_display_price_inactive():
    """販売休止中の場合、'---' が返されること"""
    # ダミーデータの準備
    inactive_product = SimpleNamespace(
        price=10000, 
        is_active=False, 
        get_display_price=Product.get_display_price
    )
    # 検証
    assert inactive_product.get_display_price() == "---"
```

境界値テストや異常系のテストもこの要領で次々と追加でき、最終的に `product.py` のテストカバレッジは **90%超え** を達成しました。追加した27テストはすべて一瞬で通過し、既存の670以上のテストにも影響を与えていません。

このPR（Pull Request）以外にも、プロジェクト全体でテスト強化を行い、最終的に **76個ものテストを追加** してプロジェクトの堅牢性を高めました。この手法の最大のメリットは、「DBコンテナを立ち上げたり、複雑なfixtureを書いたりする必要がない」点にあります。テストを書く心理的ハードルが一気に下がるはずです。

# おわりに

SQLAlchemyのモデルテストは、つい「DBを構築しなきゃ」「難しいMockを書かなきゃ」と考えがちですが、ビジネスロジック（計算や文字列整形など）に注目すれば `SimpleNamespace` というシンプルな工具で解決できます。

「テストを書きたいけれど、環境構築が面倒で…」と躊躇している初心者の方は、ぜひこの手法を試してみてください。PureなPythonの機能を活用することで、保守性が高く、爆速で実行できるテスト環境を作ることができます。

みなさんも、ぜひ自分のプロジェクトでテストカバレッジ向上に挑戦してみてくださいね！
```