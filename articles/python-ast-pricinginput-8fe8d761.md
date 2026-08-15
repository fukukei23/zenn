---
title: "【Python】AST静的検査で安全に進めるリファクタ：PricingInput参照の機械検証テスト"
emoji: "🌳"
type: "tech"
topics: ["python", "ast", "テスト", "リファクタリング"]
published: false
---

## はじめに

「リファクタの途中で一時的にデフォルト値を許容したら、戻し忘れて事故った」——こういう経験はありませんか。私が個人で開発している工房管理ツール（atelier-kyo-manager）で価格計算まわりの大規模リファクタを進めた際、まさにこの問題に直面しました。為替レートが未指定のままフォールバックで `0` として扱われ、€500 の仕入れが ¥500 の原価で計算されかける事故が発端です。

型ヒントを厳しくしても、mypy strict を導入しても、「デフォルト値のあるフィールドを渡し忘れる」という構造的な違反は検出できません。本記事では、Python 標準ライブラリの `ast` モジュールを使い、「このデータクラスの全フィールドが全呼び出し箇所で明示的に渡されているか」を機械検証する回帰テストの実装を、基礎から解説します。

## 1. 型ヒントでは防げない「渡し忘れ」

価格計算の入力は、不変な dataclass で表現していました。

```python
@dataclass(frozen=True)
class PricingInput:
    buy_price: int          # 仕入額
    shipping_fee: int       # 送料
    exchange_rate: Decimal  # 適用する為替レート
    source_url: str         # 価格の出所URL
```

ところがリファクタ中、既存コードを段階的に直すために「一部フィールドのデフォルト None を一時許容」する仕様に変更しました。

```python
@dataclass(frozen=True)
class PricingInput:
    buy_price: int | None = None
    shipping_fee: int | None = None
    exchange_rate: Decimal | None = None
    source_url: str | None = None
```

この状態は**型の世界では完全に合法**です。mypy strict は「None を扱っている箇所」は指摘できても、「呼び出し側が `exchange_rate` を渡し忘れている」ことは一切検出できません。デフォルト値がある以上、省略は正しい構文だからです。そして `exchange_rate=None` が `0` に読み替えられると円換算が暴落し、€500 が ¥500 扱いになる——これが実際に起きた問題の根っこでした。

つまり守りたいのは型ではなく構造、すなわち「全フィールドがキーワード引数で明示されている」という**呼び出し規約**です。これは人間のレビューではなく、機械に検証させたくなる要件です。

## 2. astモジュールで呼び出し箇所を機械検査する

Python の `ast` モジュールは、ソースコードをパースして木構造（Abstract Syntax Tree）に変換する標準ライブラリです。重要なのは、コードを**実行せずに**構文レベルで解析できる点。import も副作用も発生しないため、テストから安全に使えます。

```python
import ast

tree = ast.parse("result = PricingInput(buy_price=500)")
print(ast.dump(tree, indent=2))
```

出力を見ると、関数呼び出しが `ast.Call` ノードに、キーワード引数がその `keywords` 属性に入っていることがわかります。ならば「`PricingInput(...)` の Call ノードをすべて集め、keywords に必要フィールドが揃っているか確認する」テストが書けます。`ast.NodeVisitor` を継承して `visit_Call` をオーバーライドするのが定石です。

```python
import ast
from pathlib import Path

REQUIRED_FIELDS = frozenset({
    "buy_price", "shipping_fee", "exchange_rate", "source_url",
})

class PricingInputChecker(ast.NodeVisitor):
    """PricingInput の呼び出し箇所を検査するビジター"""

    def __init__(self):
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        # PricingInput(...) と models.PricingInput(...) の両方に対応
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if name == "PricingInput":
            passed = {kw.arg for kw in node.keywords if kw.arg}
            missing = REQUIRED_FIELDS - passed
            if missing:
                self.violations.append(
                    f"{node.lineno}行目: 未指定フィールド {sorted(missing)}"
                )
        self.generic_visit(node)  # ネストした呼び出しも再帰的に見る

def test_pricing_input_all_fields_explicit():
    tree = ast.parse(
        Path("app/services/pricing_service.py").read_text(encoding="utf-8")
    )
    checker = PricingInputChecker()
    checker.visit(tree)
    assert not checker.violations, "\n".join(checker.violations)
```

ポイントは3つです。

1. **実行しないので安全**：対象モジュールを import しないため、DB接続のような重い初期化を持つモジュールでも安心です
2. **`generic_visit` を呼ぶ**：Call の引数の中にさらに Call があっても再帰的に走査されます
3. **`lineno` を記録する**：違反が「何行目か」まで分かるため、修正が機械的に速い

対象パスは各自のリポジトリ構成に合わせてください。`Path("app").rglob("*.py")` で全ファイルを列挙すれば、新規ファイルが増えても自動的に検査範囲に入ります。

## 3. CIに組み込む・効果と限界

このテストは通常の pytest テストとして CI で走らせます。実際のリファクタでは次のように運用しました。

- **前半（Phase1）**：既存の6経路は修正前なので、違反リストを「既知の許容リスト」として一時管理。新規コードは即 FAIL
- **後半（Phase2）**：経路を直すたびに許容リストから削除し、最終的に空にして一時 skip も撤去
- **あわせて mypy strict を段階導入**：AST テストは「渡し忘れ」、mypy は「None の扱いミス」を守る、互いに補完する二重防壁です

効果は大きかったです。レビューで「この呼び出し、`exchange_rate` 渡してる？」と人間が見張る必要がなくなり、規約違反の PR はテストが機械的に差分を教えてくれます。為替レート 0 のサイレントフォールバック廃止（€500→¥500 事故の再発防止）も、この防壁の上で安全に実施できました。

限界も正直に書くと、文字列からの `eval` や動的生成には弱いです。また `from x import PricingInput as PI` のような別名には、checker 側に別名を登録する必要があります。ただ「普通の Python コードで書かれている限り構文木は嘘をつかない」ため、実務上は十分な検出力です。

## おわりに

`ast` モジュールは「静的解析ツールを作る人のもの」という印象がありましたが、テスト1本書くだけでも実用的な武器になります。特にリファクタ中の一時的後退（デフォルト許容・skip）を「機械的に検出可能な負債」として可視化できるのが大きいです。守りたい規約が型で表現できないなら、AST で構文を検査する——この選択肢のハードルが下がれば嬉しいです。