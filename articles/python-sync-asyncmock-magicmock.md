---
title: "【Python】非同期関数のテストをSyncにする：AsyncMock・MagicMockの実用的使い分け"
emoji: "🧪"
type: "tech"
topics: ["python", "pytest", "async", "テスト技法", "初心者向け"]
published: false
---

# はじめに

PythonでWebスクレイピングや外部APIの連携を行うシステムを開発していると、`async / await` を使った非同期処理にお世話になる機会が非常に多いです。

しかし、いざその非同期処理に対する**「テストコード」を書こうとすると、つまずく方が後を絶ちません。** `pytest`で非同期処理をテストするには `pytest-asyncio` などのプラグインを入れて、テスト関数にも `async def` をつけて……と、準備が複雑になりがちです。

今回は私が実際に開発・運用しているプロジェクト（`atelier-kyo-manager`）でのテストカバレッジ向上の取り組み（PR: run_context.py カバレッジ向上）をベースに、**非同期関数をあえて「同期的」にテストする方法**を解説します。

標準ライブラリである `unittest.mock` の `MagicMock` と `AsyncMock` をうまく使い分けることで、初心者の方でも複雑な設定なしに堅牢なテストが書けるようになります。

# MagicMockとAsyncMockの違いとは？

Pythonのテストで依存する処理を「モック（ダミー）」に置き換える際、最もよく使うのが `MagicMock` と `AsyncMock` です。

これらはとても似ていますが、**「同期処理か、非同期処理か」**という点で明確に使い分ける必要があります。

- **`MagicMock`**: 通常の関数（`def`）やクラスのモック化に使う。呼び出すと即座に固定の戻り値を返します。
- **`AsyncMock`**: 非同期関数（`async def`）のモック化に使う。呼び出すと「コルーチンオブジェクト」を返し、`await` することで本来の結果を取り出せます。

初心者の方が陥りがちな罠が、**「非同期関数を `MagicMock` でモックしてしまい、`await` でエラーになる」**というパターンです。

```python
# ❌ ダメな例：Asyncな関数をMagicMockで置き換えるとawaitできない
mock_obj = MagicMock()
mock_obj.async_method.return_value = "Result"
# 以下はエラー（TypeError: object str can't be used in 'await' expression）
result = await mock_obj.async_method() 
```

これを防ぐためには、モック対象が非同期関数である場合は、必ず `AsyncMock` を使用する必要があります。

# 非同期処理を同期的にテストする実践テクニック

では、実際の開発でどのようにテストを書くべきか見ていきましょう。

`atelier-kyo-manager` プロジェクトの中で、ブラウザ操作のコンテキストを管理する `RunContext` クラスのテストを例にします。`RunContext` はヘッドレスブラウザ（裏側で動く画面のないブラウザ）を操作し、スクリーンショットを撮る `take_screenshot` という非同期メソッドを持っています。

この非同期メソッドを含むクラスのテストを、`pytest-asyncio` に頼らずに**「同期的に」**実行するコード例をご紹介します。

```python
import asyncio
from unittest.mock import MagicMock, AsyncMock
# テスト対象のクラス（※概念サンプル）
from app.core.run_context import RunContext 

def test_take_screenshot_success():
    """take_screenshotの正常系テスト（同期テスト関数）"""
    
    # 1. テスト対象のインスタンスを生成
    context = RunContext(headless=True)
    
    # 2. 依存する外部処理（ブラウザなど）をMagicMockで生成
    mock_browser = MagicMock()
    mock_page = MagicMock()
    
    # 3. 非同期メソッドは AsyncMock で明示的にモック化する
    # ※new_page() は非同期でPageオブジェクトを返すと仮定
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    
    # 4. asyncio.run を使って非同期処理を同期的に実行し、検証する
    # context.take_screenshot 内部で await されている処理が走る
    result = asyncio.run(context.take_screenshot(mock_browser, "test_page.png"))
    
    # 5. アサーション（検証）
    assert result is True
    # 非同期メソッドが正しい引数で1回呼び出されたかを確認
    mock_browser.new_page.assert_awaited_once()
```

### ここでのポイント

#### 1. `asyncio.run()` を使った同期テスト化
テスト関数自体は通常の `def test_...` として定義します。その中で `asyncio.run()` を呼び出すことで、非同期関数のイベントループをその場で完結させ、同期的に実行できます。これにより、テスト全体の構成が非常にシンプルになります。

#### 2. オブジェクト構造に合わせた使い分け
ブラウザ全体のオブジェクト（`mock_browser`）は `MagicMock` で作成し、その中で非同期で実行されるメソッド（`new_page`）だけを `AsyncMock` に置き換えています。
このように、**「全体はMagicMock、非同期メソッドのみAsyncMock」**と組み合わせて使うのが、実務で最もスマートな使い分け方です。

#### 3. アサーションの違い
`MagicMock` が呼び出されたか確認する際は `assert_called_once()` を使いますが、`AsyncMock` の場合は `assert_awaited_once()` を使うことができます。これにより、「本当に `await` して実行されたか？」を厳密にチェックできます。

# おわりに

非同期処理のテストは「なんだか難しそう」という先入観から、後回しにされがちです。しかし、`MagicMock` と `AsyncMock` を適切に使い分け、`asyncio.run()` を組み合わせることで、同期処理と同じような感覚で直感的にテストコードが書けるようになります。

今回ご紹介した手法を取り入れた結果、実際のプロジェクトである `run_context.py` のテストカバレッジは **43% から 90%以上へと劇的に向上** しました。例外処理（エラー時の挙動）やheadlessモードの切り替えなど、細かなパターンのテストも書きやすくなります。

非同期関数のテストで躓いている方は、ぜひ今回ご紹介した同期テスト化のアプローチを試してみてください！