---
title: "【Claude Code】settings.json安全編集術：Pythonで構造を壊さずJSONを操作する具体例"
emoji: "🔧"
type: "tech"
topics: ["Python", "Claude Code", "JSON", "設定管理"]
published: false
---

## はじめに

Claude Codeを使い始めると、設定ファイルである`settings.json`をスクリプトから書き換えたくなる場面がよくあります。たとえば、複数環境への一括設定展開、CIでの設定注入、開発メンバー間の設定同期などです。

しかし、ファイルを直接書き換えようとして**カンマ忘れや括弧の対応ミスでJSONを壊してしまい、Claude Codeが起動しなくなる**——これは初心者が陥りがちな罠です。本記事では、Pythonの`json`モジュールと辞書操作を組み合わせて、構造を壊さずに`settings.json`を安全に編集する具体的手法を解説します。

## 初心者がやりがちな「文字列置換」の罠

設定ファイルの編集で一番最初に思いつくのは、`sed`やPythonの文字列`replace()`による置換でしょう。たとえば、特定のフックを追加したい場合、以下のようなコードを書いてしまいがちです。

```python
# ❌ 危険な例：文字列置換でJSONを編集
with open("settings.json", "r") as f:
    content = f.read()

# 強引にフックを差し込む
content = content.replace(
    '"hooks": {',
    '"hooks": {\n    "PreToolUse": [{"matcher": "Bash", "hooks": [...]}],'
)

with open("settings.json", "w") as f:
    f.write(content)
```

この手法には複数の問題があります。

1. **`"hooks"`キーが存在しないと置換が機能しない**
2. **すでに同じフックが存在すると重複エンゴーになる**
3. **末尾カンマの有無で構文エラーが発生する**
4. **コメント付きJSON（一部ツールが許容）に対応できない**

一番痛いのは「3番」です。置換後の文字列にカンマを付け忘れたり、逆に二重カンマになったりすると、次回の起動時に`JSONDecodeError`相当のエラーで止まります。設定ファイルが壊れると、CIが落ちる、チームメンバーが混乱する、という連鎖が起きます。

## Pythonのjsonモジュールで「構造」として扱う

安全な方針は、ファイルを「文字列」ではなく「データ構造（辞書）」として読み込み、編集してから書き戻すことです。Pythonの`json`モジュールを使えば、括弧やカンマの管理を完全に任せられます。

```python
import json
from pathlib import Path

SETTINGS_PATH = Path("/path/to/.claude/settings.json")

def load_settings(path: Path) -> dict:
    """設定ファイルを辞書として読み込む。存在しない場合は空辞書を返す。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_settings(path: Path, data: dict) -> None:
    """辞書を整形済みJSONとして書き戻す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")  # 末尾に改行を入れておくと差分が落ち着く
```

ポイントは2つです。

- `indent=2`を指定して**人間が読める形式**で書き戻すこと（後からのdiff確認が容易になります）
- `ensure_ascii=False`で**日本語等をそのまま出力**すること（エスケープシーケンスの羅列を避ける）

## 具体例：フック設定を安全に追加する

実際に「PreToolUseフックを1件追加する」処理を書いてみます。ポイントは、**既存のフックを上書きせず、追記マージする**ことです。

```python
def add_pre_tool_use_hook(settings: dict, matcher: str, command: str) -> dict:
    """PreToolUseフックを安全に追加する。

    - hooksキーが無ければ作る
    - PreToolUseキーが無ければ作る
    - 同じmatcher+commandの組合せが既にある場合はスキップ（重複防止）
    """
    hooks = settings.setdefault("hooks", {})
    pre_tool_use = hooks.setdefault("PreToolUse", [])

    new_entry = {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command}],
    }

    # 重複チェック：同じmatcherとcommandの組合せがあれば追加しない
    for existing in pre_tool_use:
        if existing.get("matcher") == matcher:
            existing_cmds = [
                h.get("command") for h in existing.get("hooks", [])
            ]
            if command in existing_cmds:
                return settings  # 何もしない

    pre_tool_use.append(new_entry)
    return settings

# 使い方
settings = load_settings(SETTINGS_PATH)
add_pre_tool_use_hook(
    settings,
    matcher="Bash",
    command="echo 'Bashフックが動作しました'",
)
save_settings(SETTINGS_PATH, settings)
```

この実装の強みは**冪等性（何度実行しても同じ結果になる）**です。文字列置換では実現が難しい性質ですが、辞書操作なら「既に存在するか？」を素直にチェックできます。CIで何度流しても同じ状態になるというのは、実運用上とても重要です。

## バックアップと検証をセットにする

どんなに気をつけても、人間はミスをします。スクリプト実行時には**必ずバックアップと構文検証を挟む**ことをお勧めします。

```python
import shutil
from datetime import datetime

def safe_update(path: Path, updater) -> None:
    """バックアップ→読込→更新→検証→書戻しをワンセットで行う。"""
    # 1. バックアップ
    if path.exists():
        backup = path.with_suffix(
            f".json.bak.{datetime.now():%Y%m%d_%H%M%S}"
        )
        shutil.copy2(path, backup)

    # 2. 読込＋更新
    settings = load_settings(path)
    updated = updater(settings)

    # 3. 検証：シリアライズできることを確認してから書き戻す
    json.dumps(updated, ensure_ascii=False)  # ここで例外が出れば書き込まない

    # 4. 書き戻し
    save_settings(path, updated)
```

このように`json.dumps()`で一度シリアライズを試しておくと、循環参照や非JSON型の値が混入した場合に**ファイルを壊す前に例外で止められます**。小さな工夫ですが、実務では何度も助けられました。

## おわりに

`settings.json`の安全な編集は、Claude Codeの運用自动化において最初の壁になります。本記事でお伝えしたかった要点は以下の3点です。

1. **文字列置換ではなく、必ず構造（辞書）として扱う**
2. **`setdefault()`と重複チェックで冪等性を担保する**
3. **バックアップと`json.dumps()`による検証をセットにする**

これらを守るだけで、CI上での設定展開やチーム展開時のトラブルが激減します。私自身も最初は文字列置換で壊して学んだクチですが、辞書操作に切り替えてからは設定ファイル破損のインシデントがゼロになりました。ぜひ自分のリポジトリでもヘルパースクリプトとして取り込んでみてください。