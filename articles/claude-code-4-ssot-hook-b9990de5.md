---
title: "Claude Code設定の事故を4層で防ぐ：SSOT生成・月次監査・hook再入制御"
emoji: "🛡️"
type: "tech"
topics: ["claude-code", "python", "gitops"]
published: false
---

## はじめに

Claude Codeを日常業務に組み込んで運用していると、設定ファイルは必ず「散らかる」ものです。CLAUDE.md、hookスクリプト、skill定義、cronジョブ……。それぞれを個別に編集し続けていると、ある日突然壊れます。私が実際に踏んだ事故は次の3つです。

- hook内のキーワード一覧に手動修正を重ねた結果、正規の生成処理と食い違う「時限爆弾」が埋まっていた
- stop hookの応答が別の処理を差し戻し、同じ指摘が**9回連続**でループした
- CLAUDE.mdに同名セクションが三重化し、どれが正しいのか分からなくなった

教訓は「人間の注意力で防ぐ事故は、必ず再度起こす」ということ。そこで設定管理を **SSOT→生成→監査→hook保護の4層** に再構築しました。本記事では各層の実装を、実際に動いているコードとともに紹介します。

## 第1〜2層：SSOT正本と生成による一元化

まず原則から。**生成物を直接編集しない**。待機応答の判定キーワードなど、hookから参照される定数は1つのJSON正本（SSOT: Single Source of Truth、単一の正本）に集め、hook本体への焼き込み（定数の埋め込み）は生成スクリプトが担います。正本と生成物の二重管理が「時限爆弾」の温床でした。

生成は fail-closed 設計——検証が通らなければ既存ファイルを一切変更しない——にしています。引用符の混入したキーワードをPythonコードに埋めると構文エラーになるからです。

```python
import json, py_compile
from pathlib import Path

SSOT = Path("/path/to/config/wait_keywords.json")
HOOK = Path("/path/to/hooks/wait_guard.py")

def bake() -> None:
    kws = json.loads(SSOT.read_text(encoding="utf-8"))["keywords"]
    seen: set[str] = set()
    purified: list[str] = []
    for kw in kws:
        kw = kw.strip()  # 注釈・空白を剥がす
        if not kw or kw in seen:
            continue  # 重複排除
        if any(q in kw for q in "\"'"):
            raise ValueError(f"引用符混入: {kw!r}")  # fail-closed
        seen.add(kw)
        purified.append(kw)

    tmp = HOOK.with_suffix(".py.new")
    tmp.write_text(render_hook(purified), encoding="utf-8")
    py_compile.compile(str(tmp), doraise=True)  # 構文検証
    rotate_backup(HOOK, generations=5)          # 5世代バックアップ
    tmp.replace(HOOK)  # ここで初めて本流を更新
```

ポイントは3つです。

1. **純化＋重複排除**：焼き込む前に `strip` と dedupe を通す
2. **`.new` に書いてから `py_compile`**：検証が落ちれば例外で終了し、現行hookは無変更のまま
3. **5世代バックアップ**：巻き戻しは世代単位で戻す

生成物の冒頭には「自動生成・直接編集禁止」のメタデータコメントも埋め込み、未来の自分（とAI）に編集先を誤解させません。このfail-closed経路（引用符混入→`.new`破棄→hook無変更）は専用テストでも保証しています。

## 第3層：月次cron監査とJSONLログ

生成で始点を守っても、運用中のドリフト（肥大化・参照切れ・重複）は別ルートで進行します。そこで**毎月5日にcronで起動する監査スクリプト**を用意し、CLAUDE.mdを3軸で機械点検しています。

- **サイズ軸**：行数・バイト数が閾値を超えたら警告
- **パス軸**：文中の参照先ファイルが実在するか
- **重複軸**：同名セクションの三重化を検出

結果は日付付きの**JSONL**に追記します。JSONLなら `jq` で時系列レビューでき、「先月緑だった項目が今月赤」のような劣化トレンドが一目で分かる。人間は月1回ログを眺めて承認するだけです。気づかないうちの設定腐敗が、この仕組みを入れてから発生していません。

## 第4層：stop_hook_activeによる再入制御

最後はhook自体の暴走防止です。stop hook内で更に処理を差し戻すと、その応答がまたstop hookを呼び、前述の9連続ループが起きました。Claude Codeは再入時に `stop_hook_active` フラグをpayloadへ渡してくれるので、これを見たら即座に抜けるガードを冒頭に置きます。

```python
import sys, json

def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("stop_hook_active"):
        return  # 再入検出: 何もせず必ず止める
    # ... 通常の待機応答判定 ...
```

わずか数行ですが、このガード追加後に同種のループは一度も起きていません。「ループが起きたら直す」のではなく「構造的に起き得ないようにする」のが正解です。

## おわりに

4層を振り返ると、すべて「**単一の正本を保ち、機械が検証し、ログが証明する**」というGitOpsの原則の適用です。

| 層 | 役割 | 実装 |
|---|---|---|
| 1 | SSOT | git管理されたJSON正本 |
| 2 | 生成 | py_compile検証＋5世代バックアップ |
| 3 | 監査 | 月次cron＋JSONLログ |
| 4 | 保護 | stop_hook_activeガード |

効果は「事故が減った」以上に、**設定変更がレビュー可能・再現可能になった**ことです。AIに設定を書き換えさせる時代だからこそ、人間は「何を正とするか」と「どう検証するか」だけを管理すればよい。この分離が、AI開発を安全にスケールさせる一番の近道だと考えています。