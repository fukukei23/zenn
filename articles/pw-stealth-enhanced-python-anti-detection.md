---
title: "playwright-stealthが開発停止なのでPython版を自作してPyPIに公開した話"
emoji: "🥷"
type: "tech"
topics: ["python", "playwright", "scraping", "stealth"]
published: true
---

## はじめに

2025年、Pythonでスクレイピングやブラウザ自動化をしているエンジニアにとって頭の痛い問題が起きました。**playwright-stealth**——WebDriverの検出を回避するために欠かせないライブラリ——の開発が停止してしまったのです。

私自身、Python×Playwrightでのブラウザ自動化案件を複数担当していましたが、playwright-stealthが止まったことでボット検知に引っかかり始めるサイトが続出しました。特にECサイトの管理画面や求人サイトなど、精巧なボット検知を採用するサービスでは顕著でした。

「じゃあ自分で作るか」という結論に至り、**pw-stealth-enhanced**を開発・PyPIに公開しました。本記事ではその背景と使い方を紹介します。

> 🔧 **開発環境の話**：このライブラリは、複数のLLMを用途別に切り替える環境で開発しました。[Claude Code CLIをGLM/MiniMaxで代替した話](https://zenn.dev/fukukei23/articles/claude-code-cost-optimization)で、そのAI駆動開発環境の構築方法を解説しています。

## 既存の状況：playwright-stealthの現状

playwright-stealthは、Node.js向けのpuppeteer-extra-plugin-stealthのPython移植版です。主に以下の検知項目に対応してきました：

- `navigator.webdriver` プロパティの検出
- Chrome拡張機能による自動化検出
- ヘッドレスブラウザ固有のプロパティ上書き

しかし、2024年後半頃からメンテナンスが滞り始め、2025年にはissueやPRが完全に放置された状態となっています。

### 現在の状況

| 項目 | 状況 |
|------|------|
| 最終更新 | 2024年夏頃（1年以上前） |
| オープンissue | 30件以上放置 |
| 新規PR | すべて未マージ |
| 対象ブラウザ | Chromium系のみ |

致命的なのは、**Canvasフィンガープリント、WebGL情報、AudioContextフィンガープリント**といった近年主流になっている検出手法に一切対応していない点です。ボット検知サービス側ではすでにこれらの高度な手法を活用しているのに、ライブラリ側のアプローチが完全に時代遅れになっていました。

## 何を作ったか：pw-stealth-enhancedの紹介

既存のplaywright-stealthの基本機能は引き継ぎつつ、現代的なボット検知に幅広く対応したステルスライブラリとして開発しました。

### コア機能一覧

#### 1. navigator.webdriver マスキング

基本中の基本。`navigator.webdriver`プロパティを`undefined`化し、自動化ツールの存在を隠します。コンテキスト生成時に確実に適用されるよう保証しています。

#### 2. Canvas フィンガープリント ノイズ注入

一番大きな改良点です。Canvasフィンガープリントは現代のボット検知で最も一般的な手法の一つで、描画時の微細な浮動小数点演算の違いを検出します。

`getImageData`呼び出し時にリアルタイムでノイズを注入し、アクセスごとに異なるCanvasフィンガープリントが生成されるようにします。

#### 3. WebGL vendor/renderer スプーフィング

WebGLフィンガープリントも重要な検出ポイントです。GPUのベンダ名とレンダラー情報を実際のブラウザ環境に準拠した値に置き換えます。

#### 4. Audio フィンガープリント 撹乱

AudioContextフィンガープリントにも対応。`OscillatorNode`等の出力に微細なノイズを加え、一貫したフィンガープリントの生成を防ぎます。

#### 5. Font 列挙スプーフィング

利用可能なフォントリストもボット検知の材料になります。正常なブラウザ環境と類似したフォントファミリー一覧を注入し、不審な一致を回避します。

#### 6. permissions.query パッチ

`Notification.permission`や`permissions.query`なども自動化検出のヒントになります。正常なユーザー行動パターンに準拠した値を返すようパッチを当てています。

#### 7. UA/Viewport ローテーションプール

ユーザーエージェントとビューポートのローテーション機能を実装。リクエストごとに異なるプロファイルを使用でき、トラッキングや個別検出を回避しやすくなります。

```python
config = StealthConfig(
    rotate_ua=True,           # UAローテーション有効
    rotate_viewport=True,     # ビューポートローテーション有効
    locale="en-US",
    timezone_id="America/New_York",
)
await apply_stealth(context, config=config)
```

#### 8. Locale/Timezone スプーフィング

`navigator.language`、タイムゾーン情報を明示的に指定可能。地域限定コンテンツのスクレイピングやローカルサービスが絡む自動化に必須の機能です。

## 使い方：5分でわかるクイックスタート

### インストール

```bash
pip install pw-stealth-enhanced
```

依存は`playwright>=1.40.0`のみ。他に必要なパッケージはありません。

### 最小構成のコード

```python
import asyncio
from playwright.async_api import async_playwright
from pw_stealth_enhanced import apply_stealth

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        # ステルスパッチを適用
        await apply_stealth(context, locale="ja-JP", timezone_id="Asia/Tokyo")

        page = await context.new_page()
        await page.goto("https://bot.sannysoft.com/")
        await page.screenshot(path="result.png")
        await browser.close()

asyncio.run(main())
```

### StealthConfigを使った詳細設定

より細かい制御が必要な場合は、`StealthConfig`オブジェクトを渡します。

```python
import asyncio
from playwright.async_api import async_playwright
from pw_stealth_enhanced import apply_stealth, StealthConfig

async def main():
    config = StealthConfig(
        rotate_ua=True,
        rotate_viewport=True,
        locale="en-US",
        timezone_id="America/New_York",
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await apply_stealth(context, config=config)

        page = await context.new_page()
        await page.goto("https://example.com")
        # ...
        await browser.close()

asyncio.run(main())
```

### コンテキスト作成と同時に適用

```python
from pw_stealth_enhanced import create_context_with_stealth

# コンテキスト作成とステルス適用を同時に
context = await create_context_with_stealth(
    browser,
    locale="ja-JP",
    timezone_id="Asia/Tokyo",
)
```

## playwright-stealthとの違い：対応項目比較

| 機能 | playwright-stealth | pw-stealth-enhanced |
|------|---------------------|----------------------|
| navigator.webdriver | ✅ | ✅ |
| Chrome拡張検出 | ✅ | ✅ |
| ヘッドレスプロパティ | ✅ | ✅ |
| Canvasフィンガープリント | ❌ | ✅ |
| WebGL vendor/renderer | ❌ | ✅ |
| AudioContextフィンガープリント | ❌ | ✅ |
| Font列挙スプーフィング | ❌ | ✅ |
| permissions.query | ❌ | ✅ |
| UAローテーション | 限定的 | ✅ 完全対応 |
| Viewportローテーション | ❌ | ✅ |
| Locale/Timezone | 限定的 | ✅ 完全対応 |

playwright-stealthのすべての機能を含みつつ、現代的なボット検知手法に完全対応しています。

## 検証方法

### bot.sannysoft.com

最も有名な自動化検出テストサイト。適用前は「WebDriver detected」「Automation detected」の赤い警告が出ますが、適用後は緑のチェックが多数を占めます。

```python
await page.goto("https://bot.sannysoft.com/")
await page.screenshot(path="sannysoft_result.png")
```

### creepjs

より高度な検出を行うサイト。Canvas、WebGL、Fontなど多角的な指標をチェックします。Canvasフィンガープリントのノイズ注入効果が顕著に現れます。

```python
await page.goto("https://abrahamjuliot.github.io/creepjs/")
```

### browserleaks.com

Canvas、Audioなど全方位的なテストを提供します。

```python
await page.goto("https://browserleaks.com/canvas")
```

> **注意**: ボット検知技術は日々進化しています。すべての検出をバイパスできるわけではありませんが、現段階の主要な検知手法には広範に対応しています。

> 📝 **開発知見の記録方法**：このライブラリの開発過程で「なぜこの実装にしたか」を属人化させずに記録する仕組みとして、SSOTを活用しています。[Claude Codeの記憶をObsidianでSSOT化する設計](https://zenn.dev/fukukei23/articles/claude-code-obsidian-ssot)でその設計思想を解説しています。

## この記事を読んで興味を持った方へ

- 📖 [Claude Code CLIをGLM/MiniMaxで代替した話](https://zenn.dev/fukukei23/articles/claude-code-cost-optimization) — このライブラリが生まれたAI駆動開発環境の構築方法を、コスト管理の観点込みで解説
- 📖 [Claude Codeの記憶をObsidianでSSOT化する設計](https://zenn.dev/fukukei23/articles/claude-code-obsidian-ssot) — AI開発での「なぜこう実装したか」を属人化させず、ナレッジとして蓄積する設計

## おわりに

`pw-stealth-enhanced`はMITライセンスで公開しています。

- **PyPI**: https://pypi.org/project/pw-stealth-enhanced/
- **GitHub**: https://github.com/fukukei23/pw-stealth-enhanced

「この検知に引っかかる」「この機能も追加してほしい」といった要望があれば、issueの報告または直接PRをお願いします。ブラウザ自動化とボット検知のいたちごっこはこれからも続きます。コミュニティの手でメンテナンスされるOSSとして、一緒に育てていきましょう。
