---
title: "orp.py 3層防御でLLMモデル照合の落とし穴を防ぐ：幽霊モデル検出の具体実装"
emoji: "👻"
type: "tech"
topics: ["Python", "ClaudeCode", "MLR", "LLM"]
published: false
---

# はじめに

Claude Code の設定を管理している自分のリポジトリで、複数のLLMにコードレビューを依頼する「マルチLLMレビュー（MLR）」を毎日運用しています。ある日、レビュー結果のログを集計していたところ、一度も依頼した覚えのないモデル名が `served_model`（実際にリクエストを処理したモデルID）として記録されていることに気づきました。**存在しないはずのモデル**——私はこれを「幽霊モデル」と呼ぶことにしました。

恐ろしいのは、レビュー本文はそれっぽい文章で返ってくる点です。照合をすり抜けると、別モデルや異常応答の結果を「正規モデルのレビュー」として信頼し、コミット判断に使ってしまいます。本記事では、この故障を防ぐためにモデル照合ユーティリティ `orp.py` に導入した **3層防御（モデル名正規化・holder突合・reason map）** の設計と、MLR v3.2.1 / v3.2.2 での実際の改修内容を初心者向けに解説します。

# 幽霊モデル故障とは何だったのか

LLM API の多くは、応答メタデータに「どのモデルが応答したか」を返します。MLRではこの値をレビュー結果とセットで記録し、後から「どのモデルの指摘か」を追跡できるようにしていました。

ところがログを確認すると、次のような記録が出てきました。

- 依頼したモデル： `gemini-2.5-pro`
- 記録されたモデル： 存在しない未知の名前

原因としては、プロバイダ側のエイリアス解決の不具合、経由するプロキシの書き換え、こちら側のフォールバック処理のバグなど複数が考えられます。しかし大事なのは原因の特定よりも、**「返ってきた名前を鵜呑みにしない」仕組み**です。従来の照合は判定結果を真偽値で返すだけで「なぜ不一致か」が残らず、さらにGemini系では応答テキストの内容に依存した脆い照合になっていました。

# orp.py の3層防御

v3.2.1〜v3.2.2 で、照合を3つの層に分けて再構築しました。

## 第1層：モデル名正規化

同じモデルでも `-preview-05-06` のような日付サフィックスや `-latest` など表記が揺れます。素朴な文字列比較では「実は同一モデルなのに不一致」と誤判定します。かといって前方一致だけで許容すると幽霊を見逃します。そこで「許されるゆらぎ」をエイリアステーブルとサフィックス除去ルールとして**明示的に列挙**します。

## 第2層：holder突合

リクエスト送信時点のモデル名を `ModelHolder` に保持し、応答の `served_model` との比較は**このholder経由でのみ**行います。比較ロジックがコード各所に散らばると、直すときにモグラ叩きになります。

## 第3層：reason map

不一致を単一の `False` にせず、`missing` / `alias` / `ghost` に分類して記録します。後から「どの理由で照合が落ちたか」を集計でき、アラートの閾値設計にも効きます。**失敗を握りつぶさず、分類して残す**のが実運用の要です。

3層を1つにまとめた実装例がこちらです。

```python
from dataclasses import dataclass

# 登録済みモデルの正規形リスト（ghost判定で使う）
KNOWN_MODELS = {"gemini-2.5-pro", "gemini-2.0-flash", "gpt-4o"}

# 表記ゆれを吸収するエイリアステーブル（第1層）
MODEL_ALIASES = {
    "gemini-2.5-pro-preview-05-06": "gemini-2.5-pro",
    "gpt-4o-2024-11-20": "gpt-4o",
}
STRIP_SUFFIXES = ("-latest", "-preview")


def normalize_model_name(name: str) -> str:
    """第1層: 表記ゆれを正規形に揃える"""
    n = (name or "").strip().lower()
    n = MODEL_ALIASES.get(n, n)
    for suffix in STRIP_SUFFIXES:
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n


@dataclass
class ModelHolder:
    """第2層: リクエスト時のモデル名を保持し、応答と突合する"""
    requested: str

    def verify(self, served_model: str | None) -> tuple[bool, str]:
        # 第3層: 不一致の理由を必ず分類して返す
        if not served_model:
            return False, "missing: served_modelが応答に含まれない"
        want = normalize_model_name(self.requested)
        got = normalize_model_name(served_model)
        if want == got:
            return True, "ok"
        if got in KNOWN_MODELS:
            return False, f"alias: 別モデル({got})が応答した"
        return False, f"ghost: 未知のモデル名({got})を検出"


holder = ModelHolder("gemini-2.5-pro")
print(holder.verify("gemini-2.5-pro-preview-05-06"))
# (True, 'ok')  ← 正規化により同一モデルと判定
print(holder.verify("gemini-3.7-nano-ghost"))
# (False, 'ghost: 未知のモデル名(gemini-3.7-nano-ghost)を検出')
```

運用では、この `verify` の結果をレビュー結果と一緒にログへ書き出し、`ghost` が発生したレビューは信頼スコアを下げて扱うようにしました。

# Gemini照合のtext非依存化（v3.2.2）

最後に残っていた脆さがGemini系の照合です。従来は「応答テキストの中にモデル名が書かれているか」を確認材料にしていました。しかしテキストはLLMの出力なので、モデルが自分の名前を書かない、別表記で書く、幻覚で別の名前を書く——すべてあり得ます。照合の成否がモデルの文章スタイルに左右されるのは設計として不安定でした。

v3.2.2 では、照合対象を**メタデータ（holder と served_model）のみに限定**し、テキストは参照しない構造に分離しました。テキスト非依存化により、Geminiの応答スタイルが変わっても照合結果が一切揺れなくなり、幽霊モデル検出が確実になりました。

# おわりに

幽霊モデル故障から学んだ教訓は3つです。

1. **外部からの返り値は、モデル名であっても信用しない** — 必ず突合する
2. **照合は単一経路（holder）に集約する** — 散らばった比較は保守不能になる
3. **失敗理由は分類して記録する** — 真偽値だけでは後から何も分析できない

これらはLLMに限らず、外部APIと疎通するあらゆるシステムに当てはまる原則だと思います。皆さんも一度、自分のLLM運用ログの `served_model` 欄を見返してみてください。意外な「幽霊」が潜んでいるかもしれません。