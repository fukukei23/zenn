---
title: "【drift_detector v1解説】AI駆動開発におけるズレ検知の設計思想：ルールベース+KPI数値評価でタスク暴走を防ぐ具体例"
emoji: "🛰️"
type: "tech"
topics: ["AI駆動開発", "Python", "Claude Code", "KPI", "Automation"]
published: false
---

## はじめに

AIエージェント（Claude Codeなど）にコードの修正や機能追加を任せる「AI駆動開発」が一般的になる中で、新たな課題が浮き彫りになっています。それは**「タスクの暴走（ズレ）」**です。

AIは与えられたタスクを忠実にこなそうとしますが、作業が長引くにつれて「本来の目的を見失い、無関係なファイルを修正し始める」「いつまでもテストを書き続ける」といった状態に陥ることがあります。

本記事では、私が自身のリポジトリで実装した**`drift_detector v1`**の内部設計を解説します。ルールベース判定とKPI数値評価を組み合わせ、AIが目的からズレ始めた瞬間を検知して停止させる仕組みを、Pythonのコード例とともにわかりやすく紹介します。

## AI駆動開発における「ズレ（Drift）」とは

ズレ（Drift）とは、AIが**「人間が意図した当初の目的」から脱線し、無関係な作業や過剰な作業を始めてしまう現象**です。

たとえば、「ボタンの色を赤に変えて」と指示したはずが、気づけば「UIフレームワークのバージョンアップ」「関連しないコンポーネントのリファクタリング」まで勝手に始めてしまうようなケースを指します。

AIが自律的に動く自動ループ処理（オートメーション）を組めば組むほど、このズレは致命的なタイムロスやバグの混入につながります。そのため、AI自身に「今の作業は本来の目的からズレていないか？」を定期的に確認させるガードレール（防護柵）が必要になります。

## drift_detector v1の設計思想

`drift_detector v1`は、AIのタスク暴走を防ぐために以下の2つのアプローチを組み合わせています。

### 1. ルールベース判定（静的チェック）
あらかじめ「やってはいけないこと」をルールとして定義しておき、AIの出力がこれに触れるかを判定します。
- 例：指定外のディレクトリのファイルを変更していないか
- 例：ループの実行回数が上限を超えていないか

### 2. KPI数値評価（動的チェック）
AIの作業状態を数値（KPI）化し、目的達成度をスコアリングします。
LLM（大規模言語モデル）を用いて「現在の目的」と「現在の作業状態」を比較させ、100点満点で評価。このスコアが一定の閾値（例：70点）を下回った場合、「目的からズレた（Driftした）」と判定します。

これらを **「⓪目的抽出 → ①計画 → ⑥ズレ検知 → ⑦記録」** という自動ループの中に組み込むことで、早期に異常を検知してAIの実行をストップさせます。

## Pythonでの実装イメージ

実際の`claude-config`リポジトリ内で動いているスクリプトの概念を抽出した、シンプルなPythonの実装例を紹介します。

```python
class DriftDetector:
    def __init__(self, target_kpi_score: int = 70):
        # 合格ラインとなるKPIスコアの閾値
        self.target_kpi_score = target_kpi_score
        # 変更を禁止するファイルやディレクトリのルール
        self.forbidden_files = [
            "/path/to/.env", 
            "/path/to/config/database.yml"
        ]

    def check_rules(self, changed_files: list) -> bool:
        """ルールベース判定: 触ってはいけないファイルを変更していないか"""
        for file_path in changed_files:
            if file_path in self.forbidden_files:
                print(f"[ALERT] ルール違反: 禁止されたファイル({file_path})が変更されました。")
                return False # ズレ（違反）を検知
        return True

    def evaluate_kpi(self, purpose: str, current_state: str) -> dict:
        """KPI数値評価: 目的と現状の一致度をLLM等でスコアリング"""
        # ※実際にはここでプロンプトを用いてLLMに評価させます
        # 今回はモックとして簡易的なスコアリングを行います
        mock_llm_score = 85 if "機能追加" in purpose else 40
        
        result = {
            "purpose": purpose,
            "current_state": current_state,
            "score": mock_llm_score,
            "is_drift": mock_llm_score < self.target_kpi_score
        }
        
        if result["is_drift"]:
            print(f"[ALERT] ズレ検知: KPIスコアが閾値を下回りました (Score: {mock_llm_score})")
            
        return result

# 実行例
if __name__ == "__main__":
    detector = DriftDetector(target_kpi_score=70)
    
    # AIが変更したファイルのリスト
    changed_files = ["/path/to/src/components/Button.tsx"]
    
    # 1. ルールベースのチェック
    is_safe = detector.check_rules(changed_files)
    
    if is_safe:
        # 2. KPI数値評価のチェック
        detector.evaluate_kpi(
            purpose="ログインボタンの色を赤に変更する",
            current_state="データベースのスキーマファイルを修正しました"
        )
```

このように、「絶対に守るべきルールのチェック」と「LLMによる柔軟なKPIスコアリング」を分離することで、誤検知を減らしつつ堅牢な監視システムを作ることができます。

## 実用例：自動ループ（auto-loop）への組み込み

この`drift_detector`は、私が運用している**NexusCore**というAI自律動作システム（自動ループ機構）に組み込んでいます。

具体的には、AIがタスクを遂行するバッチスクリプト（`run-task.sh` 等）の中で、以下のフローを回しています。

1. **⓪目的抽出**: AIにユーザーの指示を解析させ、タスクの目的とゴールを定義する
2. **①計画**: 目的を達成するためのファイル変更計画を立てる
3. **作業実行**: 実際にコードの変更やファイルの生成を行う
4. **⑥ズレ検知**: `drift_detector`を呼び出し、変更内容とKPIを評価
5. **⑦記録**: `task-log.md` というファイルに実行結果とKPIスコアを自動記録する

もし⑥のズレ検知でスコアが閾値を下回ったり、ルール違反のファイル操作が検知された場合、ループはその時点で強制終了します。これにより「帰宅してPCを見たら、数時間ずっと無関係のコードを書き続けていた」といったAI駆動開発特有の事故を完全に防ぐことができました。

## おわりに

AI駆動開発を本格的に行う so-called 「オートメーション（自動化）」において、ズレ検知はなくてはならない機能です。

`drift_detector v1`のように「ルールベース」と「KPI数値評価」を組み合わせることで、AIは安心して自律作業を続けることができます。AIに任せっぱなしにするからこそ、人間が安心できるガードレールの設計が重要になります。

皆さんのAI開発ワークフローにも、ぜひこうした「監視と停止」の仕組みを取り入れてみてください。