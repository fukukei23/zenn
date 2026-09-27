---
title: 日本語品質warn-onlyフックを3リポ同時展開した話：既存挙動を壊さない段階的ロールアウト
emoji: 🚦
type: tech
topics:
  - Claude Code
  - pre-commit
  - Python
  - warn-only
  - 段階的展開
published: false
---

# はじめに

Claude Codeに日次の記事執筆を任せている自分のリポジトリ群では、「AIが書く日本語の品質」がずっと課題でした。全角スペースの混入、句読点の連打、コードブロック内まで日本語チェックが誤爆する……。そこでpre-commitに「日本語品質警告フック」を入れることにしました。

ただし問題がひとつ。展開先の3つのリポジトリは、いずれも既存テストが緑のまま安定稼働中です。ここに新しいチェックを入れてコミットが1回でもブロックされたら、せっかくの信頼を失います。本記事では、**warn-only（警告は出すがコミットは止めない）＋ fail-open（チェック側の失敗でも止めない）** の設計で、Phase 0として3リポへ同日展開した具体的手順をまとめます。

# 1. 設計：まず「何も壊さない」ことを最優先にする

採用したのは次の3原則です。

**（1） 層1の検出器だけ有効化する**
検出器は「層1（運用実績があり誤検知ほぼゼロ）」と「層2以降（実験中）」に階層分けし、フックに入れるのは層1の2検出器だけにしました。精度が未知のルールを入れると警告がノイズになり、逆に「警告は見なくていいもの」という認識を植え付けてしまいます。

**（2） warn-only: 常時 exit 0**
何を検出しても `exit 0` を返します。警告メッセージは表示されますが、コミットは必ず通る。「警告を見て直すかどうか判断する」権利を人間（とAIエージェント）側に残す設計です。

**（3） fail-open: チェッカー自身の失敗でも止めない**
ファイルの読み込み失敗や文字コードのエラーでは、コミットを止めず「そのファイルのチェックをスキップ」します。品質チェックのせいでコミットできなくなるという本末転倒を防ぐためです。

# 2. 実装：Python製pre-commitフック

コードフェンス（``` で囲まれたブロック）内の誤検知を防ぐため、行単位の状態遷移でフェンスを除去する処理を共通モジュールとして切り出し、各リポから同じコードを参照します。リポごとに重複実装すると、「片方だけバグ修正される」事故が起きるからです。

```python
#!/usr/bin/env python3
"""日本語品質チェック: warn-only & fail-open のpre-commitフック"""
import re
import sys

# 層1（誤検知ほぼゼロ）の検出器のみ有効化
LAYER1_RULES = {
    "全角スペース": re.compile(r"\u3000"),
    "句読点の連続": re.compile(r"[。、]{2,}"),
}

def strip_code_fences(text: str) -> str:
    """```フェンス内を行単位の状態遷移で除去（共通モジュール相当）"""
    in_fence, kept = False, []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence  # フェンスの開閉を切り替え
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)

def check_file(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            text = strip_code_fences(f.read())
    except (OSError, UnicodeDecodeError) as e:
        # fail-open: チェッカー側の失敗でコミットは止めない
        print(f"[ja-quality:skip] 読み込み失敗 {path} ({e})")
        return []
    hits = []
    for name, rule in LAYER1_RULES.items():
        for m in rule.finditer(text):
            line = text[: m.start()].count("\n") + 1
            hits.append(f"{path}:{line} {name}")
    return hits

def main() -> int:
    for path in sys.argv[1:]:
        for hit in check_file(path):
            print(f"[ja-quality:warn] {hit}")
    return 0  # warn-only: 常に exit 0 でコミットを通す

if __name__ == "__main__":
    sys.exit(main())
```

続いて `.pre-commit-config.yaml` の設定です。

```yaml
repos:
  - repo: local
    hooks:
      - id: ja-quality-warn
        name: ja-quality-warn (warn-only / fail-open)
        entry: python tools/ja_quality_warn.py
        language: system
        files: \.md$
        verbose: true  # 通過時でも出力を表示（warn-onlyには必須）
```

ここで重要なのが `verbose: true` です。pre-commitは「通過したフックの標準出力をデフォルトで隠す」仕様のため、これを忘れるとwarn-onlyなのに警告が一切表示されません。warn-only設計では必須のオプションで、私も最初はこれで「警告が出ない！」と焦りました。

# 3. 3リポへの横展開手順とロールバック基準

横展開の手順は、迷いを排除するために事前に4ステップで固定しました。

1. **共通モジュールの切り出し**： フェンス判定をリポ間で重複実装しないよう単独ファイル化する
2. **パイロットリポで検証**： まず1リポに投入し、既存テストが全緑のままコミットできることを確認する
3. **同日展開**： 残り2リポへ同じコード・同じコミットメッセージで投入する。「検証済みバージョンと未検証バージョンが混在する期間」を作らないためです
4. **ロールバック基準を先に文書化**： 展開前に「いつ戻すか」を判断基準ごと決めておきます

ロールバック基準（該当したら即時実施）は次の3つです。

- **コミットが1回でもブロックされた**（warn-onlyの約束違反なので設計欠陥）
- **pre-commit自体がエラーで止まる・タイムアウトする**（fail-openの約束違反）
- **誤検知が1日5件を超える検出器が出たら、その検出器だけ無効化**

ロールバックの実体はconfigから該当フックを削除するだけなので数分で完了します。「戻し方が簡単であることを先に確認しておく」——これは慎重に見えて、実は最速の変更管理です。

# おわりに

warn-onlyは一見「何も変わらない」施策に見えます。しかし実際に3リポへ展開してみると、警告ログから検出器ごとの誤検知率がデータとして蓄積され、将来fail（コミット阻断）に昇格すべき検出器が数字で判断できるようになります。また、Claude CodeのようなAIエージェントがコミットする運用では、AIの書いた日本語が人間が見る前に自動チェックされる体制ができました。

既存が緑のリポジトリに手を入れるときは、まず「壊さない」を保証してから「良くする」。この公務員みたいな回り道が、結局いちばん速いのだと実感した展開でした。次はPhase 1として層2検出器の追加と、溜まったデータに基づくfail化の検討を進める予定です。