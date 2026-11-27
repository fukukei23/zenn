---
title: "AIの失敗を知識に変える話：FKB学習ループと二段承認をPythonで実装"
emoji: "🧠"
type: "tech"
topics: ["Claude Code", "AI駆動開発", "Python", "テスト設計"]
published: false
---

## はじめに

Claude Codeを使い、12体のエージェントが協調してコード生成〜レビュー〜コミットまで回す自律開発パイプライン「NexusCore」を構築している。しかし設計書には「12エージェント協調」と書いてあるのに、実は**postmortem・knowledge_curator・policy_agentの3体は一度も配線されていなかった**。「設計にはあるが動いていない」——典型的なドキュメントと実装のズレだ。

さらに運用で刺さった問題が2つあった。

1. **AIが同じ失敗を繰り返す**。昨日importエラーで詰まった箇所に、今日また詰まる。失敗ログは残っているのに誰も読み返さない
2. **承認の穴**。品質レビュー担当のguardianが承認すればコミットが通る仕組みになっており、方針違反チェックを後回しにできてしまった

今回、3体を実際に配線し、この2問題を「失敗学習ループ（FKB）」と「二段承認ゲート」で解決した。その設計とコードを紹介する。

## 1. 失敗を知識に変える：FKB学習ループ

FKBはFailure Knowledge Base（失敗知識ベース）の略。**失敗の教科書データベース**だ。ループは3体で構成する。

- **postmortem**: テストがfailのまま修正試行を使い切った（失敗枯渇）状態を検知し、失敗を解剖する事故調査官
- **knowledge_curator**: 分析が正しいか・既存知識と重複しないかを検証する司書
- **中央FKB**: 検証済み知識を永続化する保管庫。debuggerエージェントが次回から参照する

永続化されるレコードはこんな形だ（簡略化）。

```python
fkb_record = {
    "id": "FKB-0142",
    "failure_signature": "ImportError: No module named 'code_generator'",
    "root_cause": "UI統合で旧モジュールは削除済みだが、"
                  "開発ツール側に残存importがあった",
    "countermeasure": "エントリポイント棚卸しで到達不能パスを一括削除",
    "status": "verified",  # knowledge_curatorの検証を通過
    "source": "postmortem: test_failure_exhausted",
}
```

ポイントは `status: "verified"` だ。postmortemの出力を無審査で溜めると、**間違った原因分析が「知識」として蓄積され、むしろ毒になる**。だから検閲役を挟んでいる。人間の組織でいう「ポストモーテムをリードがレビューしてから社内Wikiに載せる」のと同じ構造だ。このレコードは実際に起きた失敗（存在しないモジュールへの残存import）が元になっており、同じ種類の失敗は以後FKBヒットで数分で解決するようになった。

## 2. 二段承認：policy_agentをコミットゲートへ

2つ目の問題は承認フローだ。当初の実装はこうだった。

```python
# ❌ 修正前: guardian承認だけで通過してしまっていた
def review_and_commit(self, change, guardian_result):
    if guardian_result.approved:
        return ReviewResult(ReviewStatus.APPROVED, "guardian承認済み")
    # policyチェックはguardian拒否時にしか到達しない…
```

guardianは品質は見るが、方針違反（秘密情報のハードコードや禁止領域への書き込み）は担当外。つまり「二段承認」のはずが**どちらか一方がOKなら通過するOR条件**になり、最終レビューで発見したときは背筋が寒くなった。

修正後はAND条件にした。

```python
from dataclasses import dataclass
from enum import Enum

class ReviewStatus(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

@dataclass
class ReviewResult:
    status: ReviewStatus
    reason: str

class PolicyAgent:
    """コミット承認ゲート: guardian承認 AND policy準拠で初めて許可"""

    def review_and_commit(self, change, guardian_approved: bool) -> ReviewResult:
        # 1段目: guardianの品質承認
        if not guardian_approved:
            return ReviewResult(ReviewStatus.REJECTED, "guardian未承認")

        # 2段目: policy違反チェックはguardian承認に関係なく毎回走る
        violations = self.check_policy