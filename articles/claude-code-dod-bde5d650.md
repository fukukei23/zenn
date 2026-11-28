---
title: 「記録した」だけで完了にしない：Claude Codeの判断ログをDoDで検証する
emoji: 📝
type: tech
topics:
  - claude-code
  - ssot
  - yaml
  - 業務改善
published: false
---

## はじめに

公務員として勤務していた頃、こんな空気がありました。

**「書類の欄が全部埋まっていれば、その仕事は完了」**

稟議書でも報告書でも、欄が埋まっていれば「やった」とみなされがちでした。中身が実効性を持っているか、実施した事実と整合しているかは、二の次にされやすい。

いま私はClaude Codeの運用ノウハウを、GitHub上でストーリー形式（1エピソード1ファイル）で管理しています。各ストーリーの判定結果は `judgment-log.yaml` という判断ログに追記していく運用です。ここで気づいたのは、公務員時代と同じ罠がYAMLでも再現されるということでした。

**「エントリを追記した」≠「判定が完了している」**

この記事では、記録（.record）を完成品とみなさず、DoD（完了の定義）で検証する仕組みを、実際に踏んだ失敗とともに紹介します。

## 「書類が埋まっている＝完了」と同じ罠がYAMLにもある

### 罠1：追記したのに、読めないログになっていた

あるストーリーの判定を判断ログに追記した日のことです。コミットは成功し、ファイルにも新しいエントリが入っていました。翌日、別の判定を追記しようとしたときに気づきました。**前日のエントリがYAMLとしてパースできていなかった**のです。

原因は、フロー形式（`{key: value}` の波かっこ記法）に長い文章を詰め込んだことでした。

```yaml
# NG: フロー形式でクォートしていないコロンを含む文章
- {story_id: 074, note: 印刷機: 補正ONで成功}  # 2つ目のコロンで構文エラー

# OK: ブロック形式＋文字列はクォート
- story_id: "074"
  note: "印刷機: 補正ONで成功"
```

欄は埋まった。でもそのログは「機械が読めないテキストの塊」でした。修復コミットを打つまで半日以上、壊れた状態が放置されていた計算です。まさに公務員の書類と同じ構図です。

### 罠2：記録表が満点でも、実質2日なら達成ではない

別の運用の第8回判定で、項目ごとのチェック表はすべて埋まっていました。見た目は満点です。

しかし実施記録を遡ると、実際に運用を続けていたのは**2日だけ**。週次で回すと決めていた運用なら、2日で「達成」と判定するのは誤りです。

**表が埋まっていること**と**実施事実が続いていること**は別物です。前者を後者の代理にしてしまうのが、公務員業務で学んだ最大の教訓でした。

## 判断ログのDoD（完了の定義）を先に決める

「記録した」を完了にしないためには、**完了の定義（DoD: Definition of Done）を先にコードで書ける形で決めてしまう**のが有効です。私の判断ログでは、エントリ1件が「完了」と言える条件を次のように定めました。

1. YAMLとしてパースできる（構文的に正しい）
2. 必須フィールド（対象story・判定日・結果・実施日数）が揃っている
3. 判定結果が実施日数と矛盾しない（満点でも2日なら達成にしない）
4. 複数storiesを一括追記した場合、全エントリが同じ水準を満たす

重要なのは、このDoDを**人間の判断に頼らず機械で検証する**ことです。「ちゃんと埋まった気がする」という感覚は信用しません。

## Pythonで「記録が機能しているか」を機械的に検証する

先のDoDをそのままPythonに落とします。ポイントは2つです。

- `yaml.safe_load` が失敗した時点で「読めない書類」として即エラー（罠1の対策）
- `result` と `duration_days` の矛盾を検出（罠2の対策）

```python
import sys
from datetime import date

import yaml

# 判断ログのDoD（完了の定義）
REQUIRED_FIELDS = ["story_id", "judged_at", "result", "duration_days"]
# 「達成」と言える最低実施日数（例: 週次運用なら5日）
MIN_DURATION_DAYS = 5


def validate_entry(entry: dict) -> list[str]:
    """エントリ1件がDoDを満たすか検証し、違反メッセージを返す"""
    errors = []

    # DoD 2: 必須フィールドが揃っているか
    for field in REQUIRED_FIELDS:
        if field not in entry:
            errors.append(f"必須フィールド '{field}' がありません")

    # 判定日は ISO 8601 (YYYY-MM-DD) であること
    try:
        date.fromisoformat(entry["judged_at"])
    except (KeyError, ValueError, TypeError):
        errors.append("judged_at が ISO 8601 形式ではありません")

    # DoD 3: 記録表が満点でも実質期間が足りなければ達成ではない
    if entry.get("result") == "achieved":
        days = entry.get("duration_days") or 0
        if days < MIN_DURATION_DAYS:
            errors.append(
                f"result=achieved だが duration_days={days}"
                f"（最低 {MIN_DURATION_DAYS} 日必要）"
            )
    return errors


def main(path: str) -> int:
    # DoD 1: そもそもYAMLとして読めるか（構文壊れの対策）
    try:
        with open(path, encoding="utf-8") as f:
            log = yaml.safe_load(f) or {}  # 空ファイル対策
    except yaml.YAMLError as e:
        print(f"[構文エラー] パースに失敗しました: {e}")
        return 1

    has_error = False
    for i, entry in enumerate(log.get("judgments", []