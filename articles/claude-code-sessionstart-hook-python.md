---
title: "【Claude Code】SessionStart hookで始める状態管理入門：セッション引継ぎをPythonスクリプトで実装する具体例"
emoji: "🪝"
type: "tech"
topics: ["Claude Code", "hook", "Python", "初心者向け", "状態管理"]
published: false
---

# はじめに

Claude CodeをCLIで使い続けていると、こんな悩みにぶつかりませんか？

- 前回どこまで作業したか忘れてしまう
- 毎回同じコンテキストを手動で説明している
- プロジェクトの前提条件を都度思い出すのが面倒

そんな課題を解決するのが **SessionStart hook** です。本記事では、`hooks.yaml`による設定とPythonスクリプトを組み合わせて、セッション開始時に前回の状態を自動で読み込む仕組みを初心者向けに解説します。実際の運用で使っている知見を交えて具体的に紹介しますので、hooks入門の参考にしてください。

# SessionStart hookとは？

## hookの基本

Claude Codeのhookは、特定のタイミングで任意のコマンドやスクリプトを実行できる仕組みです。主な種類は以下のとおりです。

| hook名 | 実行タイミング |
| --- | --- |
| SessionStart | 新しいセッション開始時 |
| PreToolUse | ツール実行前 |
| PostToolUse | ツール実行後 |
| Stop | 応答完了時 |

中でも **SessionStart** は、セッションが始まった直後に実行されるため、前回の状態復元や環境確認に最適です。

## なぜ状態管理にhookが有用なのか

手動で「前回やったこと」をメモして運用する場合、以下の問題が起きます。

- メモを見返す手間がかかる
- 書き忘れが発生する
- チームで運用するとフォーマットがバラバラになる

hookに任せれば、**セッションを開くだけで必要な情報が自動でコンテキストに渡る**ため、認知負荷が大きく下がります。

# 実践：hooks.yamlとPythonでセッション引継ぎを実装する

ここからは具体例を見ていきましょう。今回は以下の2ファイル構成で実装します。

```
/project-root/
├─ .claude/
│  └─ hooks.yaml
├─ scripts/
│  └─ session_restore.py
└─ state/
   └─ last_session.json
```

## 1. hooks.yamlの設定

まずはhookの登録です。Claude Codeが認識する設定ファイルに、SessionStart時の実行コマンドを書きます。

```yaml
# hooks.yaml の例
hooks:
  SessionStart:
    - command: "python3 /path/to/scripts/session_restore.py"
      timeout_ms: 3000
```

ポイントは以下の2点です。

- **タイムアウトを明示する**: スクリプトが重いとセッション開始がブロックされるため、上限を設けます
- **絶対パスで指定する**: 作業ディレクトリに依存しないよう、パスは固定します

## 2. Pythonスクリプトで状態を読み込む

続いて、前回の状態ファイルを読み込んで標準出力に吐くPythonスクリプトを書きます。標準出力の内容がそのままClaudeのコンテキストに渡るのがこのhook最大の特徴です。

```python
#!/usr/bin/env python3
"""SessionStart hook: 前回のセッション状態を復元する"""
import json
import sys
from pathlib import Path

STATE_FILE = Path("/path/to/state/last_session.json")

def load_state() -> dict:
    """状態ファイルを読み込む。未存在時は空dictを返す。"""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # JSON破損時は警告だけ出して継続
        print(f"[session_restore] 警告: 状態ファイルの読み込みに失敗 ({e})", file=sys.stderr)
        return {}

def render(state: dict) -> str:
    """状態をコンテキストに渡すテキストに整形する。"""
    if not state:
        return "前回の状態情報はありません。"
    lines = ["## 前回セッションの引き継ぎ情報", ""]
    lines.append(f"- 最終作業日時: {state.get('last_updated', '不明')}")
    lines.append(f"- 作業ブランチ: {state.get('branch', '不明')}")
    lines.append(f"- 残タスク: {state.get('remaining_tasks', 'なし')}")
    if state.get("notes"):
        lines.append("")
        lines.append("### メモ")
        lines.append(state["notes"])
    return "\n".join(lines)

def main():
    state = load_state()
    # 標準出力がそのままClaudeのコンテキストに渡る
    print(render(state))

if __name__ == "__main__":
    main()
```

このスクリプトの肝は、**「状態を読み込んで整形してprintする」だけのシンプルな構造**にしている点です。複雑な処理を詰め込むとメンテナンス性が下がるため、本番運用でもこのくらいシンプルに保つことをお勧めします。

## 3. 状態ファイルの書き込み

状態ファイルは、セッション終了時や作業区切りのタイミングで更新します。手動でも良いですし、Stop hookで自動書き込みする運用も可能です。

```json
{
  "last_updated": "2026-07-13T10:30:00+09:00",
  "branch": "feature/add-hook-docs",
  "remaining_tasks": "hooks.yamlのテスト追加・ドキュメント整備",
  "notes": "check-proxy-combat.shの検証が途中。次回は続きから。"
}
```

# 実務で使うためのベストプラクティス

最後に、実際の運用で効いた工夫を3つ紹介します。

## 1. エラーは握りつぶさずstderrに出す

スクリプトが例外で落ちた場合、何も出力されないと「状態が読み込まれたのかどうか」が分かりません。上記の例でも `sys.stderr` に警告を出していますが、これはClaudeのコンテキストを汚さずに人間が気づけるようにするためです。

## 2. 状態ファイルはバージョン管理する

`state/last_session.json` はGitで追跡すると、過去に戻りたい時に便利です。ただし機密情報は含めないよう注意し、必要に応じて `.gitignore` で制御してください。

## 3. 出力サイズを抑制する

SessionStart hookの出力が大きすぎると、本来使えるはずのコンテキストを圧迫します。目安として **500トークン程度**に収まるよう、項目を厳選しましょう。「あったら便利」ではなく「必須か」で判断すると良いです。

# おわりに

SessionStart hookとPythonスクリプトを組み合わせれば、Claude Codeのセッション引継ぎを半自動化できます。今回紹介した構成は非常にシンプルですが、それゆえに保守しやすく、最初の一手として最適です。

まずは「前回の作業ブランチと残タスクだけ表示する」ような小さなスクリプトから始めてみてください。運用しながら足りない情報を足していくと、自分のワークフローにフィットした状態管理が育っていくはずです。

本記事の知見は、実際のClaude Code運用ガイド整備の中で得たものです。hooks設定の詳細や他のhook活用例については、随時アップデートしていく予定です。ぜひご自身の環境でも試してみてください。