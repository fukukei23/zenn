---
title: 【Claude Code】shadow→enforce昇格プロセス入門：誤検知ゼロを達成した段階的導入の具体手順
emoji: 🚦
type: tech
topics: [ClaudeCode, hook, gate-design, fail-safe]
published: false
---

## はじめに

Claude Codeのhookで「危険な操作をブロックするゲート」を作るとき、一番怖いのは**誤検知**です。正当な作業が1回止まるだけで、そのゲートへの信頼は失われ、外されてしまいます。

本記事では、warn-only（shadow）モードで運用していたfail-safe-gateを、**shadow判定3回連続成立・誤検知ゼロ**の実績を条件にenforce（強制ブロック）へ昇格させた実例を、判定条件の数値化から夜間ループCLIへの統合まで解説します。

## 1. shadowモードで安全に始める

fail-safe-gateは「条件を満たさない書き込みを検知したら止める」PreToolUseフックです。導入当初は、判定結果をログに残すだけのshadowモードで動かしました。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/fc_guard.py --mode shadow"
          }
        ]
      }
    ]
  }
}
```

shadowモードでは、ゲートが「ブロック対象」と判定してもexit codeは常に0を返し、判定理由だけを記録します。Claude Codeの作業は一切止まりません。この間に「本来止めるべきケース（真陽性）」と「止めてはいけないケース（誤検知）」の両方を観測し、判定ロジックの精度を上げていきます。

## 2. 昇格判定の3条件を数値で固定する

「なんとなく調子が良いからenforceにしよう」を防ぐため、昇格条件を最初から数値で固定しました。

1. shadow判定が**3回連続で成立**（真陽性を正しく検知できている）
2. **誤検知ゼロ**（block相当の判定が正当作業で出ていない）
3. 想定シナリオd1〜d5の**全経路で観測済み**

```python
from dataclasses import dataclass

REQUIRED_SCENARIOS = {"d1", "d2", "d3", "d4", "d5"}

@dataclass
class ShadowLog:
    scenario: str   # d1〜d5のどの経路か
    passed: bool    # shadow判定が成立したか
    blocked: bool   # block相当の判定が出たか（誤検知の疑い）

def can_promote(logs: list[ShadowLog]) -> tuple[bool, str]:
    if len(logs) < 3:
        return False, "shadow判定が3回未満"
    if not all(l.passed for l in logs[-3:]):
        return False, "3回連続成立していない"
    if any(l.blocked for l in logs):
        return False, "block相当（誤検知疑い）あり"
    missing = REQUIRED_SCENARIOS - {l.scenario for l in logs}
    if missing:
        return False, f"未観測シナリオ: {sorted(missing)}"
    return True, "3点成立・enforce昇格可"
```

ポイントは**判定をコードに落とす**ことです。昇格の議論が主観ではなく「ログと条件の照合」だけになります。さらにこの判定結果をレビュー担当（ふくけい）に提示して承認をもらう運用にしました。「数値条件＋承認」の二段構えで、勢いによる昇格を防いでいます。

## 3. shadow期間中に誤検知を潰す：d5分割書込の実例

shadowモードの価値は「本番で事故る前に誤検知を見つけられる」ことです。実際、第3回shadow判定の事前分析で、d5（分割書込）経路の誤発火を発見しました。

原因は、1つのファイルを複数回に分けて書き込むケースで、**途中の中間body（書きかけの状態）をAST評価してしまい**、未完成のコードを不正な書き込みと誤判定していたことです。

修正方針は「同一スキャン内では、ファイル毎の**最終bodyのみ**をAST評価する」と一本化。TDDで再現テストから書き、12テストすべて緑になった時点で取り込みました。この誤検知を潰した直後に第3回shadow判定が成立し、3点が揃いました。初日からenforceだったら、この誤検知で正当な作業が止まっていたはずです。

## 4. enforce化と夜間ループCLI統合

3点成立＋承認を得て、ゲートをenforceモードへ昇格しました。切替は`--mode enforce`の1引数のみで、判定コード本体は一切変えません。ロールバックも引数を戻すだけです。

enforce化に合わせ、夜間の自動作業ループ（CLI）にも同じゲートを統合しました。夜間は誰も見ていない時間帯なので、ゲートの存在意義が最も大きくなります。日中の対話セッションと夜間ループで同一の判定ロジックを共有することで、「昼は通るのに夜は止まる」といった不整合も起きません。

## おわりに

誤検知ゼロでenforceに到達できたのは、以下の段階的導入のおかげです。

- shadowモードで実際の作業を止めずに観測する
- 昇格条件（3回連続・誤検知ゼロ・経路網羅）を数値で固定する
- 判定はコードで、最終承認はレビュー担当の二段構え
- モード切替は引数1つで、ロールバック容易に保つ

このプロセスはhookに限らず、CIゲートやデプロイガードなど「止める系の自動化」全般に適用できるパターンです。ブロック系機能を導入するときは、ぜひshadow期間から始めてみてください。