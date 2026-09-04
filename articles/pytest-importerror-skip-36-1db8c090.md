---
title: "【pytest】ImportErrorで全skipされた36テストを救う：意図的削除関数の正しい整理法"
emoji: "🚑"
type: "tech"
topics: ["pytest", "Python", "リファクタリング"]
published: false
---

## はじめに

God Class（巨大クラス）を責務ごとに分割するリファクタリングを行った数日後のことでした。ふとCIを確認すると、あるテストファイルの**36テスト全てがskip**になっていました。スキップは「失敚」ではないのでCIは緑のまま。誰も気づかないまま放置されていたのです。

本記事では、この「機械的にskipされるテスト」の原因特定から復旧、再発防止までの実録を解説します。

## なぜ36テストが沈黙したのか：原因特定

該当テストファイルの冒頭に、こんなコードがありました。

```python
import pytest

try:
    from myapp.llm.legacy import generate_test, validate_profile
except ImportError:
    pytest.skip("legacy module is unavailable", allow_module_level=True)
```

`pytest.skip(allow_module_level=True)` は、オプション依存のライブラリが無い環境でテスト一式をスキップさせる常套句です。書いた当時は意味がありました。

しかしリファクタリングで `legacy` モジュールが**意図的に削除**された結果、このtry/exceptは常にスキップ側に落ち、ファイル内の36テストが丸ごと実行されない状態になっていたのです。

skipの理由を確認するには `-rs` オプションが有効です。

```bash
$ pytest tests/test_legacy.py -rs
36 skipped, 0 passed in 0.12s
SKIPPED [36] test_legacy.py: legacy module is unavailable
```

## 復旧の3ステップ

### ステップ1: 削除済み関数のimportを消す

まず `try/except ImportError` のガードごと削除しました。存在しない関数をimportし続ける限り、このファイルは永久にスキップされます。

### ステップ2: 旧契約のテストはテストも消す

36テストの内訳を精査すると、2種類に分かれました。

- **削除された関数の契約を検証するテスト** → 分割時に新モジュール側へ移植済みだったので、旧テストはごっそり削除
- **移動先でも有効なテスト** → 新モジュールのテストファイルへ移植

「関数を消したら、そのテストも消す/移す」は当たり前の話ですが、skipに隠れているとこの整理が先送られ、気づいた時には「何が正だったか分からない」状態になりがちです。

### ステップ3: @patchの対象を実呼び出し元に修正

移植したテストで最後にハマったのがmockのpatch先です。`unittest.mock.patch` は「**その名前が実行時にlookupされる場所**」を指定しなければなりません。

```python
# ❌ 旧: 定義されていたモジュールを指しており、実行時にmockされない
@patch("myapp.llm.legacy.get_client")

# ✅ 新: 実際に呼び出されるモジュール側をpatchする
@patch("myapp.llm.providers.openai.get_client")
def test_generate_test(mock_client):
    result = generate_test(prompt="hello")
    mock_client.assert_called_once()  # 空転検知も添える
    assert result is not None
```

特に危険なのは、古いパスが偶然残存しているケースです。エラーにならずmockが一度も使われない「空転テスト」になり、テストが通っていても何も検証していません。`assert_called_once()` を添えると空転を検知できます。

## 再発防止：skipを「見える化」する

skipはCIを赤にしないため、放置すると静かに腐ります。そこでCIに簡単なゲートを入れました。

```bash
# 予期しないskipが1件でもあったらジョブを落とす
if pytest -q --tb=no | tail -n 2 | grep -E "[0-9]+ skipped"; then
  echo "::error::予期しないskipを検出しました"
  exit 1
fi
```

正当な理由（依存ライブラリ不在など）でskipするテストが増えたら、閾値をベースラインとして明示的に更新します。ポイントはskip件数を**継続的な監視対象に置く**こと。「0が理想だが、増えたら必ず理由を説明できる状態」を保つのが目標です。

## おわりに

今回の対応で学んだことは3つです。

- ImportErrorガードのmodule-level skipは、削除済みモジュールをimportし続ける限りテストを永久に沈黙させる
- 関数を意図的に削除したら、**import・旧契約テスト・@patch先の3点セット**で整理する
- skip件数はCIで監視し、増加分には必ず理由がある状態を保つ

リファクタリングでテストが減るのは致し方なくても、「気づかないうちに消える」のは防げます。同じ轍を踏む方の一助になれば幸いです。