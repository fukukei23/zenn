---
title: "4,000行のPythonファイルをMixinで分割した話"
emoji: "🐍"
type: "tech"
topics: ["python", "refactoring", "design-patterns", "clean-code"]
published: false
---

## はじめに

4,000行超のPythonファイル、どうしてますか？

1つの巨大なクラスに全部放り込むと、どこに何があるか分からなくなる。かといって無造作にファイルを分けると、既存のimportが全部壊れる。

この問題を解決した Mixin + 純粋関数抽出パターンを、具体的なコードと一緒に紹介します。

## 対象: 4,212行の navigation_driver.py

BUYMA×Buyandship転売管理のWebスクレイピング自動化プロジェクトで、こんなコードがありました。

```python
# navigation_driver.py（リファクタリング前: 4,212行）
class NavigationDriver:
    # --- URL正規化 ---
    def normalize_url(self, url): ...
    def extract_domain(self, url): ...
    def is_same_origin(self, url1, url2): ...

    # --- PLP巡回 ---
    def crawl_plp(self): ...
    def extract_product_links(self): ...
    def detect_last_page(self): ...

    # --- PDP抽出 ---
    def extract_title(self): ...
    def extract_price(self): ...
    def extract_images(self): ...

    # --- エッジケース ---
    def handle_popup(self): ...
    def handle_consent_banner(self): ...
    def retry_with_backoff(self): ...

    # ...400メソッド以上
```

全部が1ファイルにある。メソッド間の依存が密で、切り出すのが怖い状態でした。

## Mixinパターンを選んだ理由

Pythonで巨大なクラスを分割する方法はいくつかあります。

| 方法 | メリット | デメリット |
|---|---|---|
| モジュール分割（通常） | シンプル | メソッド共有が面倒 |
| ユーティリティ関数 | 強力だが別問題 | 状態を持つメソッドは分離困難 |
| Mixinクラス | 複数Mixinを継承して1クラスにできる | 銀の弾丸ではない |
| Decorator | 関数拡張向き | 状態共有が複雑 |

**Mixinが最適だった理由**: ブラウザ操作の状態（self.driver, self.page, self.site_config）を複数の責務間で共有する必要がある。Mixinなら `self` を通じて自然に状態にアクセスできる。

## 実装方法

### Step 1: Mixinクラスを定義する

```python
# nav_types.py — データクラス定義
from dataclasses import dataclass
from enum import Enum

@dataclass
class NavigationContext:
    url: str
    page: Any  # Playwright page
    driver: Any  # Playwright browser

class NavigationOutcome(Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
```

```python
# nav_fallbacks.py — フォールバックロジック
class FallbackMixin:
    """エラー時のフォールバック戦略"""

    def handle_timeout(self) -> bool:
        """タイムアウト時のリトライ"""
        for attempt in range(self.max_retries):
            try:
                return self._retry_navigation()
            except TimeoutError:
                continue
        return False

    def handle_popup(self) -> bool:
        """ポップアップ閉じる"""
        try:
            self.page.locator("[aria-label='閉じる']").click()
            return True
        except Exception:
            return False
```

### Step 2: 継承で合成する

```python
# navigation_driver.py — 分割後（239行）
from .nav_types import NavigationContext, NavigationOutcome
from .nav_fallbacks import FallbackMixin
from .locale_manager import LocaleMixin
from .moncler_nav import MonclerNavMixin

class NavigationDriver(
    FallbackMixin,       # エラー処理
    LocaleMixin,         # ロケール判定
    MonclerNavMixin,     # ブランド固有処理
):
    """
    Mixin合成で責務を分割。
    各Mixinはself経由でdriver/page/site_configにアクセス可能。
    """
    def __init__(self, config):
        self.driver = config["driver"]
        self.page = config["page"]
        self.site_config = config["site_config"]

    # 核心ロジックのみ残す
    def navigate(self, url: str) -> NavigationOutcome:
        try:
            self.page.goto(url)
            self._wait_for_content()
            return NavigationOutcome.SUCCESS
        except TimeoutError:
            if self.handle_timeout():
                return NavigationOutcome.SUCCESS
            return NavigationOutcome.TIMEOUT
```

### Step 3: 純粋関数を 적극抽出する

Mixinにできない処理（ `self` に依存しない計算ロジック）は、純粋関数として分離します。

```python
# url_rules.py
def extract_etld_plus_one(hostname: str) -> str | None:
    """URLからETLD+1を抽出。self不要。"""
    from urllib.parse import urlparse
    # ... 実装
    return etld_plus_one

def normalize_url(url: str) -> str:
    """URL正規化。純粋関数。"""
    # ... 実装
    return normalized
```

```python
# navigation_driver.py 内
class NavigationDriver(FallbackMixin, ...):
    def navigate(self, url: str):
        # 純粋関数呼び出し
        normalized = normalize_url(url)
        domain = extract_etld_plus_one(normalized)
        # ...
```

### Step 4: 後方互換性を保つ（最重要）

既存のコードが `from app.agents.browser.navigation_driver import NavigationDriver` で動いていた場合、分割後にこれを壊すとユーザーが困る。

```python
# navigation_driver.py
from .nav_types import (
    NavigationContext, NavigationOutcome, LinkCandidate
)
from .url_rules import (
    extract_etld_plus_one, normalize_url, validate_url
)

# 後方互換のため、nav_typesのクラスを再エクスポート
__all__ = [
    "NavigationDriver",
    "NavigationContext",  # nav_typesから
    "NavigationOutcome",  # nav_typesから
    "extract_etld_plus_one",  # url_rulesから
    "normalize_url",  # url_rulesから
]
```

テストは既存のimportのまま動きます:

```python
# テストは変更不要
from app.agents.browser.navigation_driver import NavigationDriver
from app.agents.browser.navigation_driver import NavigationOutcome

# NavigationOutcomeはnav_typesからきているが、正しくimportできる
```

## 成果: 4,212行 → 239行

| ファイル | 分割前 | 分割後 | 削減率 |
|---|---|---|---|
| navigation_driver.py | 4,212行 | 239行 | **94%** |
| 分割先 | — | 5ファイル | — |
| plp_driver.py | 1,344行 | 272行 | **80%** |
| 分割先 | — | 6ファイル | — |

## テストは壊れていないか？

**壊れていません。**

分割前と分割後で全テスト同一パス。理由は:

1. `__all__` で後方互換exportを提供
2. Mixin継承の `self` が自然に動作
3. 純粋関数は副作用なしの独立モジュール

```bash
# 分割前も分割後も同じ結果
pytest tests/ -q
# ✅ 886 passed → ✅ 886 passed（回帰なし）
```

## 設計原則まとめ

### ✅ やったこと

1. **単一責務Mixin**: 1つのMixinは1つの責務のみ持つ
2. **純粋関数抽出**: `self` に依存しないロジックは関数に
3. **明示的export**: `__all__` で後方互換を確保
4. **既存テスト維持**: importパス変更不要

### ❌ やらなかったこと

1. **状態を持たないMixin**: Mixinが独自stateを持つと予期せぬ相互作用
2. **循環import**: 各Mixin間の依存を排除
3. **無差別分割**: 「大きいから分割」ではなく「責務で分割」

## まとめ

```
4,212行ファイル
  ├─ 継承(Mixin) → 状態共有のロジック
  └─ 純粋関数   →  statelessなロジック
  └─ re-export  →  後方互換維持
```

Pythonの多重継承は怖くない。正しく使えば、4,000行の混沌も239行のクリーンなコードになります。
