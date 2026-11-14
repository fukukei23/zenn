---
title: Claude Codeのコンテキスト浪費を防ぐ全記録：使用量注入・警告・節約術
emoji: 📊
type: tech
topics:
  - claude-code
  - context-management
  - hooks
  - tdd
published: false
---

## はじめに

Claude Codeを長く使っていると必ずぶつかるのが「コンテキスト過積載」です。気がつけばauto-compactが発動して、せっかく積み上げた会話履歴が要約に置き換わっていた──。`/context`コマンドで手動確認するのも、集中していると忘れてしまいます。

そこで自分の設定リポジトリに、2つのhookを組み合わせた仕組みを作りました。

1. **context-usage-inject**: 毎ターンの使用量を自動でコンテキストに注入
2. **警告hook**: 閾値超過を検知して「そろそろ圧縮or新規セッション」と促す

さらに、cache_readの課金構造を公式ドキュメントと実測値で照合し、ログ解析の落とし穴（1MB境界・usage欠落行）はTDDで固めました。その全記録を紹介します。

## 1. 毎ターン使用量を注入する UserPromptSubmit フック

Claude Codeのhooksには **UserPromptSubmit** というタイミングがあります。プロンプトを送るたびに1回だけ実行され、stdoutに出した文字列がシステムコンテキストとして追加される仕組みです。

stdinにはJSONが渡ってきて、`transcript_path`（セッションの会話ログJSONL）が取れます。集計の骨子はこんな感じです。

```bash
#!/usr/bin/env bash
input=$(cat)
transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
[ -z "$transcript" ] && exit 0

# 巨大化したログ対策: 最新1MBだけを窓に読む
ctx=$(tail -c 1048576 "$transcript" | jq -rs '
  [ .[] | select(.message.usage != null)
         | .message.usage
         | (.input_tokens + .cache_read_input_tokens
            + .cache_creation_input_tokens) ] | max // 0
')
echo "context usage: ${ctx} tokens"
```

これで毎ターン「いま何トークン消費しているか」がClaude自身にも見えるようになり、「残り容量を意識して」「不要なファイルは読まないで」といった指示が実際に守られやすくなりました。

警告側は同じ集計で閾値（70%）を超えたら「`/compact` か新規セッションを推奨」という警告文を注入するだけ。シンプルですが、auto-compact発動の「知らないうちに履歴が要約されていた」事故がほぼなくなりました。

## 2. cache_read の課金構造を公式ドキュメントと実測値で照合

節約の前に、料金の仕組みを正しく理解します。usageオブジェクトには4種類のトークン数が入っています。

- `input_tokens`: 新規入力
- `cache_read_input_tokens`: キャッシュヒットした分
- `cache_creation_input_tokens`: キャッシュに書き込んだ分
- `output_tokens`: 出力

公式ドキュメントによると、**cache readは通常入力の10%の価格**です（入力が$3/MTokならcache readは$0.30/MTok）。つまりコンテキストが大きくても、キャッシュにヒットし続ける限り課金は軽い。逆に5分以上操作を空けるとキャッシュが切れ、全文が通常入力として課金されます。

実測照合用の計算式がこちらです。

```python
PRICE = {  # Sonnet系の目安 ($/MTok)
    "input": 3.0,
    "cache_read": 0.3,     # 公式: 入力の10%
    "cache_write": 3.75,
    "output": 15.0,
}

def cost_usd(u: dict) -> float:
    m = 1_000_000
    return (
        u.get("input_tokens", 0) * PRICE["input"]
        + u.get("cache_read_input_tokens", 0) * PRICE["cache_read"]
        + u.get("cache_creation_input_tokens", 0) * PRICE["cache_write"]
        + u.get("output_tokens", 0) * PRICE["output"]
    ) / m
```

この式で1日分のJSONLを合計したところ、管理画面の請求額とほぼ一致しました（ズレの主因はauto-compact直後の大量cache miss）。ここから得た節約の要点は次の2つです。

- 用事の合間にセッションを切り替えず、続けてキャッシュを温存する
- 閾値警告が出たら、auto-compactに任せるより意図的に `/compact` か新規セッションへ分割する

## 3. TDDで守るログ解析：1MB境界・usage欠落行・日跨ぎ集計

地味に効いたのがここです。冒頭の `tail -c 1048576` には落とし穴が2つあります。

1. 行の途中で1MB境界が来る（先頭行が壊れたJSONになる）
2. `usage` フィールドが存在しない行が混ざる

この2つをテストファーストで潰しました。

```python
import json

def collect_usages(raw: bytes) -> list[dict]:
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if lines and not lines[0].lstrip().startswith("{"):
        lines = lines[1:]  # 境界で切れた行を破棄
    usages = []
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # usage欠落・空行は無視
        msg = obj.get("message")
        u = msg.get("usage") if isinstance(msg, dict) else None
        if isinstance(u, dict):
            usages.append(u)
    return usages

def test_boundary_and_missing_usage():
    broken = b'{"partial": tru'  # ちょうど境界で切れた行
    ok = json.dumps({"message": {"usage": {
        "input_tokens": 10,
        "cache_read_input_tokens": 100,
        "output_tokens": 5}}}).encode()
    got = collect_usages(b"\n".join([broken, ok]))
    assert len(got) == 1
```

さらに日跨ぎ問題もあります。日次で使用量を集計すると、午前0時を跨ぐセッションが両日に重複計上されたり取りこぼされたりします。そこで **session_id単位の全期間（Lifetime）集計を正** とし、日次はその差分ビューに切り替えました。警告hook側でも「警告付きで通過」した記録がpassと二重計上されないよう、テストで境界条件を固定しています。最終的にこのhook周りは70を超えるテストが緑になりました。

## おわりに

振り返ると、コンテキスト浪費対策はたった3つの積み重ねでした。

1. **見える化**： 毎ターン使用量を注入（UserPromptSubmit）
2. **防御**： 閾値警告でauto-compact事故を未然に防ぐ
3. **理解**： cache_readの課金構造を実測と照合し、節約の方向を決める

どれもhooksとJSONLの集計だけで作れて、特別なAPIは不要です。「気がついたら圧縮されてた」を卒業したい方は、まず使用量注入の1本から試してみてください。