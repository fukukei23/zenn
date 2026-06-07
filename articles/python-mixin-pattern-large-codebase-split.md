---
title: "Mixinで4,000行Pythonクラスを整理した"
emoji: "🐍"
type: "tech"
topics: ["python", "refactoring", "design-patterns", "clean-code"]
published: false
---

## はじめに

「4,000行のクラスがあります。責務は5つ。どう分割しますか？」

正直に答えます。最初はファイルを分けて「終わり！」と思っていました。でも既存のimportが全部壊れる。テストも全部落ちる。怖くなって元に戻したこともある。

結果的に選んだのは **Mixin + 純粋関数抽出 + 再エクスポート** の組み合わせです。4,212行が239行になって、テストは1行も壊れませんでした。

具体的な手法と、「これでよかったこと」「あえてやらなかったこと」を全部話します。

## 対象: 4,212行の navigation_driver.py

BUYMA×Buyandship転売管理のWebスクレイピング自動化プロジェクトで発生しました。

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

    # --- ブランド固有処理 ---
    def handle_moncler_redirect(self): ...
    def handle_gucci_spa(self): ...

    # --- エラー処理 ---
    def handle_popup(self): ...
    def handle_consent_banner(self): ...
    def retry_with_backoff(self): ...

    # ...400メソッド以上
```

全部が1ファイルにある。どのメソッドがどの責務に属しているか、ファイル名からは分からない。

## なぜMixinなのか

Pythonでクラスを分割する主な選択肢は以下の3つです。

| 方法 |  состояние共有 | 再利用性 | 既存import |
|---|---|---|---|
| 通常モジュール分割 | × 面倒 | ◎ | ❌ 全部壊れる |
| Composition（集約） | ○ 渡せる | △ 面倒 | ◎ そのまま |
| **Mixin（注入）** | **◎ self経由** | **◎ 継承で注入** | **◎ 再エクスポート** |

**Mixinが最適だった条件**:
- ブラウザ操作の状態（`self.driver`, `self.page`, `self.site_config`）を複数の責務間で共有する必要がある
- 責務ごとにメソッド群が独立している
- テストが既存のimportパスに依存している

## 設計方針3つ

### 方針1: Mixinはstatelessにする

**最も重要なルールです。**

```python
# ✅ 良い例: selfは読むが、独自stateを持たない
class FallbackMixin:
    def handle_timeout(self) -> bool:
        for attempt in range(self.max_retries):
            try:
                return self._retry_navigation()
            except TimeoutError:
                continue
        return False
```

```python
# ❌ 悪い例:Mixinが独自stateを持つと競合する
class BadFallbackMixin:
    def __init__(self):
        self._retry_count = 0  # 危険！他のMixinや親クラスと競合
```

Mixinが独自の`__init__`を持たなければ、MRO（後述）の順序に依存せず、安全に合成できます。

### 方針2: 純粋関数を 적극抽出する

`self` を1度も呼ばないロジックは迷わず関数にします。

```python
# url_rules.py — 純粋関数のみ
def extract_etld_plus_one(hostname: str) -> str | None:
    """URLからETLD+1を抽出"""
    from urllib.parse import urlparse
    return etld_plus_one(hostname)  # 依存ライブラリに丸投げ

def normalize_url(url: str) -> str:
    """URL正規化"""
    # ...実装
    return url.strip().lower()
```

```python
# navigation_driver.py 内
class NavigationDriver(FallbackMixin, LocaleMixin):
    def navigate(self, url: str) -> NavigationOutcome:
        normalized = normalize_url(url)      # 純粋関数
        domain = extract_etld_plus_one(normalized)  # 純粋関数
        self.page.goto(domain)
        return NavigationOutcome.SUCCESS
```

### 方針3: 再エクスポートで後方互換を確保する（最重要）

既存のコードが `from app.agents.browser.navigation_driver import NavigationDriver` で動いていた場合、分割後にこれを壊すとユーザーが困る。

```python
# navigation_driver.py
from .nav_types import NavigationContext, NavigationOutcome, LinkCandidate
from .url_rules import extract_etld_plus_one, normalize_url, validate_url
from .nav_fallbacks import FallbackMixin
from .locale_manager import LocaleMixin

# nav_types のクラスを navigation_driver から再エクスポート（後方互換）
__all__ = [
    "NavigationDriver",
    "NavigationContext",  # nav_typesから
    "NavigationOutcome",  # nav_typesから
    "LinkCandidate",      # nav_typesから
    "extract_etld_plus_one",  # url_rulesから
    "normalize_url",      # url_rulesから
]
```

```python
# テストは既存のimportのまま動きます
from app.agents.browser.navigation_driver import NavigationDriver
from app.agents.browser.navigation_driver import NavigationOutcome  # nav_types由来だがOK
```

## 実装: 4ステップ

### Step 1: データクラス・型定義を分離

```python
# nav_types.py — 型定義のみ。ロジックなし。
from dataclasses import dataclass
from enum import Enum

@dataclass
class NavigationContext:
    url: str
    page: Any
    driver: Any

class NavigationOutcome(Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"

class RejectReason(Enum):
    POPUP = "popup"
    CONSENT = "consent"
    TRAP = "trap"
```

### Step 2: Mixinクラスを定義

```python
# nav_fallbacks.py — フォールバックロジック
class FallbackMixin:
    """エラー時のフォールバック戦略。self.page/self.driver/self.max_retriesを使用。"""

    def handle_timeout(self) -> bool:
        for attempt in range(self.max_retries):
            try:
                self._retry_navigation()
                return True
            except TimeoutError:
                continue
        return False

    def handle_popup(self) -> bool:
        try:
            self.page.locator("[aria-label='閉じる']").click()
            return True
        except Exception:
            return False
```

```python
# locale_manager.py — ロケール判定
class LocaleMixin:
    """サイトlocale判定ロジック"""

    def detect_locale(self) -> str:
        html = self.page.content()
        if "lang=ja" in html:
            return "ja"
        if "lang=en" in html:
            return "en"
        return "unknown"
```

### Step 3: 継承で合成

```python
# navigation_driver.py — 分割後（239行）
from .nav_types import NavigationContext, NavigationOutcome
from .nav_fallbacks import FallbackMixin
from .locale_manager import LocaleMixin
from .moncler_nav import MonclerNavMixin

class NavigationDriver(
    FallbackMixin,    # エラー処理
    LocaleMixin,      # ロケール判定
    MonclerNavMixin,  # ブランド固有処理
):
    """
    Mixin合成で責務を分割。
    各Mixinはself経由でdriver/page/site_configにアクセス可能。
    """
    def __init__(self, config: dict):
        self.driver = config["driver"]
        self.page = config["page"]
        self.site_config = config["site_config"]
        self.max_retries = config.get("max_retries", 3)

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

### Step 4: MROを意識する

Pythonの多重継承には **MRO（Method Resolution Order）** があります。Mixinが同名メソッドを持つ場合、左から優先されます。

```python
class A:
    def greet(self): return "A"

class B:
    def greet(self): return "B"

class C(A, B):  # MRO: C → A → B
    pass

print(C().greet())  # "A"（Aが優先）
```

Mixin間での同名メソッド衝突を避けるため、**Mixinのメソッド名は一意にします**:

```python
# nav_fallbacks.py
class FallbackMixin:
    def _handle_timeout_impl(self) -> bool: ...  # 内部実装
    def handle_timeout(self) -> bool:  # 外部API
        return self._handle_timeout_impl()
```

## 成果: 4,212行 → 239行

| ファイル | 分割前 | 分割後 | 削減率 |
|---|---|---|---|
| navigation_driver.py | 4,212行 | **239行** | **94%** |
| plp_driver.py | 1,344行 | **272行** | **80%** |

## テストは壊れていないか？

**壊れていません。**

```bash
pytest tests/ -q
# ✅ 886 passed → ✅ 886 passed（回帰なし）
```

理由は3つ:
1. `__all__` で後方互換exportを提供
2. MixinはstatelessなのでMRO順序に依存しない
3. 純粋関数は副作用なしの独立モジュール

## やってよかったこと

1. **責務が可視化された**: `nav_fallbacks.py` を開けばエラー処理だけが見える
2. **テストが書きやすくなった**: 各Mixinは独立しているので отдельно тестировать
3. **新ブランド追加が楽になった**: `MonclerNavMixin`, `GucciNavMixin` を継承に追加するだけでOK

## あえてやらなかったこと

1. **Mixin間の相互呼び出し**: Mixin AからMixin Bのメソッドを呼ばせない。循環依存防止
2. **状態を持つMixin**: 独自`__init__`を持たせない（前述）
3. **無差別な細分化**: 「責務として独立しているか？」を必ず自問

## まとめ

```
4,212行ファイル
  ├─ Mixin継承 → selfを共有する責務ロジック
  ├─ 純粋関数  → self不要な計算ロジック
  └─ 再エクスポート → importパス変更ゼロ
```

Pythonの多重継承は銀の弾丸ではありませんが、条件が揃えば非常に強力です。4,000行の混沌を整理したいけど「ファイルを分けると壊れる」が怖い、という方に届けば幸いです。
