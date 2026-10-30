---
title: "AIには画像が見えるのか：Claude Codeの画像・動画読解を盲検で検証する"
emoji: 🔍
type: tech
topics:
  - Python
  - Claude Code
  - AI評価
published: false
---

## はじめに

「AIに画像は見えない」――そう信じて運用していた。自分が管理するClaude Code設定用リポジトリのドキュメントにも「vision非対応」と明記し、画像解析が必要なタスクは外部のマルチモーダルモデルへ委任する設計にしていた。

ところが2026年10月、不可解な現象に遭遇した。スライド画像を渡しただけの会話で、AIがスライド内の細かい文字を正確に引用してきたのである。「見えないはずのものが、見えていた」。

この矛盾を放置すると、トラブル時の原因切り分けが永遠にあてにならなくなる。そこで、同一の画像・動画を複数の経路に投入して比較する**盲検実験**を設計した。本記事では、(1) 比較した4つの読解経路、(2) 再現可能なPython判定スクリプト、(3) 実測で判明したこと、を順に紹介する。

## 1. 盲検実験の設計：4経路 × 同一入力

実験の骨子はシンプルだ。

- 入力をすべての経路で完全に同一にする（同一のPNGスライド、同一の短いMP4動画）
- 正解キーワードを実験**前に**テキストで確定する（後付けの正当化を防ぐ）
- AI側には「内容をそのまま報告して」とだけ指示し、正解に関するヒントを一切与えない
- 判定は人間の印象ではなく機械的に行う

なぜ「盲検」にこだわるのか。AIは会話の流れや文脈からの推測で、妙にそれっぽい答えを返すことがある。「画像を見えた」と言っているように見えて、実は周辺の手がかりで言い当てただけ、という可能性を排除したいのだ。だから正解は事前に封筒に入れて（比喩です）、出力と突き合わせる形にした。

比較したのは次の4経路だ。

1. **GLM-5.3-Flashへの直接API呼び出し**
2. **MiniMax-M3による直接読解**
3. **Claude CodeのReadツール経路**（プロキシでモデル切替を行う構成を通る）
4. **媒体API呼び出し**（画像・動画解析用に作成したスクリプト経由）

3つ目の「Read経路」が曲者で、裏でプロキシがモデルを切り替える構成になっているため、外から見える挙動と実際に応答しているモデルが一致する保証がない。だからこそ、他の3経路と同じ入力で横並び比較する必要があった。

## 2. Python判定スクリプト

判定は「事前定義キーワードの再現率」で行う。全角半角のゆらぎで誤判定しないよう、NFKC正規化を挟むのが実用上のポイントだ。

```python
import json
import unicodedata
from pathlib import Path

TRUTH_KEYWORDS = ["量子もつれ", "測定問題", "2026年度計画"]  # 実験前に確定

def normalize(s: str) -> str:
    """全角半角・空白のゆらぎを潰してから比較する"""
    return unicodedata.normalize("NFKC", s).replace(" ", "")

def load_response(route: str) -> str:
    """各経路の応答ログ(JSON)から本文だけを取り出す"""
    raw = Path(f"results/{route}.json").read_text(encoding="utf-8")
    return normalize(json.loads(raw)["content"])

def blind_score(text: str) -> dict:
    hits = [kw for kw in TRUTH_KEYWORDS if normalize(kw) in text]
    return {"score": len(hits) / len(TRUTH_KEYWORDS), "hits": hits}

routes = ["glm_direct", "minimax_read", "claude_read", "media_api"]
report = {r: blind_score(load_response(r)) for r in routes}

for route, r in sorted(report.items(), key=lambda x: -x[1]["score"]):
    hit_str = " / ".join(r["hits"]) or "なし"
    print(f"{route:14s} 再現率 {r['score']:.0%}  命中: {hit_str}")
```

出力のイメージはこうなる（数値は説明用のサンプル）。

```text
glm_direct     再現率 100%  命中: 量子もつれ / 測定問題 / 2026年度計画
minimax_read   再現率 100%  命中: 量子もつれ / 測定問題 / 2026年度計画
claude_read    再現率  67%  命中: 量子もつれ / 測定問題
media_api      再現率 100%  命中: 量子もつれ / 測定問題 / 2026年度計画
```

ここで大事なのは、スコアは「読めた証拠の強さ」であって文章の品質ではない、ということ。部分一致ベースの単純な判定だからこそ、誰が実行しても同じ結果になる再現性が手に入る。

## 3. 実測結果：前提は覆った

結果を要約すると次のとおりだ。

- **GLM-5.3-Flash**は、画像・動画ともキーワードを高率で再現した。直接API呼び出しで視認できている
- **MiniMax