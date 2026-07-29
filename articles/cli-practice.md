---
title: "【CLI監視ツール設計】ヘルスチェック実装入門：ソース別成功率集計で異常を自動検知"
emoji: "🩺"
type: "tech"
topics: ["python", "cli", "監視", "例外処理"]
published: false
---

## はじめに

WebサイトのスクレイピングやAPI経由でデータを収集するCLIツールを開発・運用する際、最も恐れるのは「知らぬ間にツールが動かなくなり、重要な情報を取りこぼしていること」です。

例えば、筆者が最近開発した「複数のWebサイトから特定商品の抽選情報を収集し、Discordに通知するCLIツール」では、直リンク（2経路）とRSSフィード（4経路）の合計6つの異なるソース（データ取得元）から情報を集めていました。

このような複数ソースを束ねるツールでは、特定のサイトだけがHTML構造を変えてエラーになる、あるいは一時的にサーバーがダウンするといったケースが日常茶飯事です。すべてのエラーで通知を飛ばすとノイズになりますし、逆に無視し続けると「気づいたら1ヶ月間、メインの情報源だけ取得できていなかった」といった事故に繋がります。

そこで今回は、CLIツール自身に**「健全性を監視するヘルスチェック機能」**を組み込む方法を解説します。ソースごとの成功率を集計し、閾値（50%以下）を下回った場合に警告を出す具体的な実装例を紹介します。

## ソース別成功率集計の設計思想

ヘルスチェックといっても、単に「直近の実行が成功したか失敗したか」だけを見るのは危険です。一時的なネットワークの乱数や、サイトの一時的なメンテナンスでエラーになることはよくあるからです。

そこで、以下のような要件で設計しました。

1. **ソース別（URLやサイトごと）に集計する**
   全ソースを合わせた全体の成功率を見ても、「どのサイトが死んでいるのか」がわかりません。ソースごとに成功・失敗のカウンタを用意します。
2. **一定数の履歴（サンプル）を元に算出する**
   最新の1回だけで判定すると、一時的なエラーで過剰に反応してしまいます。直近N回分の結果を保持し、その中での成功率を計算します。
3. **50%以下で警告を出す**
   「何回かに1回程度のエラーなら許容するが、半分以上失敗するならサイト構造が変わった（またはサーバーが死んでいる）疑いがある」という基準で閾値を設定しました。

## Pythonでのヘルスチェック実装例

それでは、実際にPythonを使って「ソース別成功率集計」を行うヘルスチェックモジュールを実装してみましょう。

ここでは、直近の実行結果をキュー（リスト）で保持し、指定したサンプル数での成功率を計算するシンプルなクラスを作成します。

```python
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class HealthChecker:
    def __init__(self, sample_size: int = 10, threshold: float = 0.5):
        """
        :param sample_size: 成功率を計算するための直近の履歴保存数
        :param threshold: 警告を出す成功率の閾値（0.5 = 50%）
        """
        self.sample_size = sample_size
        self.threshold = threshold
        # ソース名ごとに成功・失敗の履歴を保存する辞書
        # 例: {"source_A": deque([True, False, True, ...])}
        self.history = defaultdict(lambda: deque(maxlen=self.sample_size))

    def record_result(self, source_name: str, is_success: bool):
        """
        データ取得の結果を記録する
        """
        self.history[source_name].append(is_success)

    def check_health(self) -> list[str]:
        """
        各ソースの健全性をチェックし、警告メッセージのリストを返す
        """
        warnings = []

        for source_name, results in self.history.items():
            # サンプル数が足りない場合はスキップ（初動起動時など）
            if len(results) < self.sample_size:
                continue

            total = len(results)
            success_count = sum(1 for r in results if r)
            success_rate = success_count / total

            # 成功率が閾値以下の場合、警告を生成
            if success_rate <= self.threshold:
                msg = (
                    f"【ヘルスチェック警告】ソース '{source_name}' の成功率が低下しています。"
                    f"(成功率: {success_rate:.0%}, 閾値: {self.threshold:.0%})"
                )
                logger.warning(msg)
                warnings.append(msg)

        return warnings
```

### CLIツールのメインループへの組み込み

この `HealthChecker` を実際のCLIツールの例外処理に組み込みます。データ取得処理を `try-except` で囲み、結果を記録していくだけのシンプルな実装です。

```python
def fetch_data_from_source(source_name: str, url: str, checker: HealthChecker):
    """
    各ソースからデータを取得するモック関数
    """
    try:
        # ここで requests.get やスクレイピング処理を行う
        response = some_fetch_logic(url)
        response.raise_for_status()
        
        # HTMLのパース等に成功した場合は成功を記録
        checker.record_result(source_name, is_success=True)
        
        return response.data

    except Exception as e:
        # ネットワークエラーやパースエラーが発生した場合は失敗を記録
        logger.error(f"ソース '{source_name}' でエラー発生: {e}")
        checker.record_result(source_name, is_success=False)
        return None

def main():
    # ヘルスチェッカーの初期化（直近10回の履歴、閾値50%）
    checker = HealthChecker(sample_size=10, threshold=0.5)
    
    sources = {
        "kidsrepublic": "https://example.com/source1",
        "livepocket": "https://example.com/source2",
        # ...その他のソース
    }

    # CLIツールの定期実行ループ（例：1時間に1回など）
    for _ in range(daily_iterations):
        for name, url in sources.items():
            fetch_data_from_source(name, url, checker)
        
        # 1ループ終了ごとに健全性を評価
        active_warnings = checker.check_health()
        
        if active_warnings:
            # 警告がある場合はDiscordやSlackに通知する処理を呼ぶ
            send_alert_to_discord("\n".join(active_warnings))
```

## 閾値「50%」の根拠と運用上の工夫

実務でこの機能を運用するにあたり、いくつか工夫を施しています。

### 1. なぜ「50%」という甘い閾値なのか？
Webサイトのスクレイピングでは、アクセス集中によるタイムアウト（503エラー）や、一時的なサーバーエラー（500エラー）が日常的に発生します。閾値を「90%」などに設定すると、こうした一時的な揺らぎで頻繁にアラートが飛んでしまい、いわゆる「アラート疲れ」を引き起こします。

「10回中5回失敗する（成功率50%）」という状態は、一時的なエラーではなく**「WebサイトのHTML構造が変わってパースに失敗し続けている」**可能性が極めて高い状態です。そのため、確信を持って警告を飛ばせるラインとして50%を採用しました。

### 2. 初動起動時の誤爆防止
コード例にも記載しましたが、`len(results) < self.sample_size` の条件でガードをかけています。CLIツールを再起動した直後など、履歴が2〜3回しかない段階で1回失敗すると成功率が50%を下回ってしまうため、指定したサンプル数（10回）が溜まるまでは判定を行わないようにしています。

### 3. 未知のエラーに対する「安全側」の実装
新しいソース（例えば `Livepocket` 等の新しい抽選サイト）を追加した際、最初から完璧なパース処理（正規表現やHTMLパーサーの設定）を書くのは困難です。
「取得できたらラッキー」「取得できなくても全体の動作は止めない」といった「安全側」に倒した実装を行いつつ、ヘルスチェックで「そのソースだけ正常に機能していない」ことを自動検知することで、放置による機会損失を防ぐ設計にしています。

## おわりに

今回は、複数ソースからデータを収集するCLIツールに健全性を監視するヘルスチェック機能を実装する方法を解説しました。

- **ソース別に直近の成功率を集計する**
- **一定のサンプル数を溜めてから判定する**
- **異常時は継続して動かしつつ、外部（Discord等）に警告を投げる**

このような仕組みを導入することで、ツールを「放置しても安心できる」状態に近づけることができます。アラートの閾値設計などは、実際の運用環境のネットワークの安定性に合わせて調整してみてください。

CLIツールの信頼性向上に悩まれている方の参考になれば幸いです。