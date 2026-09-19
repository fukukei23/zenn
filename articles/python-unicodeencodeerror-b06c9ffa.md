---
title: "【Python】孤立サロゲートでUnicodeEncodeErrorを防ぐ：ログ保存前の無害化実装"
emoji: "🛡️"
type: "tech"
topics: ["Python", "Unicode", "エラーハンドリング", "ロギング"]
published: false
---

## はじめに

自分のリポジトリで運用しているタスク実行ロガー（task_logger）で、ある日「特定のタスクのログだけ保存に失敗する」事故が起きました。スタックトレースには見慣れないメッセージが並んでいます。

```
UnicodeEncodeError: 'utf-8' codec can't encode character '\udc80':
surrogates not allowed
```

犯人は**孤立サロゲート（lone surrogate）**——UTF-8としては存在してはいけない文字データが、外部コマンドの出力経由でログ文字列に混入していました。しかも被害はクラッシュだけではありません。保存処理が死ぬことで**そのログ自体が失われる**という二次被害もあり、事故調査を困難にします。

本記事では、孤立サロゲートがなぜUTF-8保存を壊すのか、そして保存前に無害化する関数をTDD（テスト駆動開発）の「赤→緑」で実装した内容を紹介します。

## 孤立サロゲートとは？——なぜUTF-8保存で死ぬのか

Unicodeの世界では、絵文字など一部の文字をUTF-16で表現する際に、**サロゲートペア**という2つの値の組みを使います。

- 上位サロゲート： `U+D800〜U+DBFF`
- 下位サロゲート： `U+DC00〜U+DFFF`

この2つは「必ずペアで使う」前提の仕様で、片方だけでは文字としての意味を持ちません。しかし現実には、バイト列の途中切断、破損したJSONの `\udXXX` エスケープ、`surrogateescape` でデコードした外部コマンド出力など、**ペアの片方だけが紛れ込む**ことは意外と起こります。この「はぐれた片割れ」が孤立サロゲートです。

厄介なのは、Pythonの `str` が内部表現の都合上、孤立サロゲートを**エラーなしに保持できてしまう**こと。つまり文字列を受け取った時点では何も起きず、いざファイル保存で `encode("utf-8")` が走った瞬間に爆発します。

```python
text = "task finished: \udc80"  # 下位サロゲート1文字だけ混入
text.encode("utf-8")
# UnicodeEncodeError: 'utf-8' codec can't encode character
# '\udc80' ...: surrogates not allowed
```

「普段は動くのに、特定の入力の時だけ保存が死ぬ」という再現性の低いバグになるのはこのためです。

## 対策：保存前に無害化する関数を作る

対策の選択肢は大きく2つあります。

**① 正規表現でサロゲート領域を置換する**

```python
import re

# サロゲート領域（U+D800〜U+DFFF）
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

def sanitize_for_write(text: str) -> str:
    """UTF-8で書き込めない孤立サロゲートを置換文字に置き換える。"""
    return _SURROGATE_RE.sub("\ufffd", text)
```

**② encodeのerrorsオプションに任せる**

```python
def sanitize_for_write(text: str) -> str:
    # backslashreplaceなら \udc80 という「見える文字列」になり、
    # 何が混入したのか後からログで追跡できる
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")
```

今回は②を採用しました。ログはデバッグの証拠なので、異常データを単なる「?」に潰すより、`backslashreplace` で**混入物の正体を可視化**しておく方が調査に有利だからです。

なお `open()` に `errors="backslashreplace"` を渡す方法もありますが、これは書き込み箇所すべてで指定漏れが出やすいのが弱点です。**保存直前に呼ぶ明示的な関数**として切り出すことで、どの保存経路でも同じ無害化が効き、かつ単体テスト可能になります。呼び出し側はこうなります。

```python
def save_log(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(sanitize_for_write(text))
```

## TDDで「赤→緑」を確認する

この修正はテストファーストで進めました。まず期待を書いたテストを用意します。

```python
import pytest
from task_logger import sanitize_for_write

def test_normal_text_is_kept():
    # 正常なテキストは一切変更されない
    assert sanitize_for_write("task done") == "task done"

def test_lone_surrogate_is_neutralized():
    cleaned = sanitize_for_write("log\udc80tail")
    cleaned.encode("utf-8")          # 例外が出なければ保存成功
    assert "\udc80" not in cleaned

def test_save_survives_surrogate(tmp_path):
    path = tmp_path / "result.log"
    path.write_text(sanitize_for_write("ok\udc80"), encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "ok\\udc80"
```

次に、`sanitize_for_write` をまず**何もしない実装**（`return text` のみ）で用意してテストを実行します。すると `test_lone_surrogate_is_neutralized` が `UnicodeEncodeError` で落ちます。これが**赤**です。

この一手間には意味があります。「テストが本当に事故を再現できているか」を、修正前に確認できるからです。テストが落ちた状態を見てから、本実装（`backslashreplace` による置換）を入れて再実行。全テストが通り**緑**になりました。

赤を飛ばして緑だけ見ると、「たまたま通っているだけ」のテストを見抜けません。数行の関数でも赤緑を踏む価値は十分あります。

## おわりに

今回の学びをまとめます。

- 孤立サロゲートはPythonの `str` 内では沈黙し、UTF-8保存の瞬間にだけ `UnicodeEncodeError` を起こす「遅延爆弾」である
- 外部コマンド出力など信用できない入力は、**保存という境界**で無害化するのが有効
- ログ処理は本体の処理より長生きすべきもので、ログが落ちると事故調査そのものができなくなる
- `backslashreplace` で異常データを可視化すれば、無害化しつつ調査材料も残せる

エンコードまわりのバグは「普段は動く」ので見落としがちです。ログ保存に限らず、外部入力をファイルに書き出す処理を持っている方は、一度 `sanitize` 関数を挟むことを検討してみてください。