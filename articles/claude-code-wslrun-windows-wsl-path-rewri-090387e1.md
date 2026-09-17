---
title: 【Claude Code】wslrunディスパッチャでWindows-WSL相互運用：path-rewriteフック回避の具体設計
emoji: 🐧
type: tech
topics: ["ClaudeCode", "WSL", "Windows", "Python", "bash"]
published: false
---

## はじめに

Windows Desktop版のClaude CodeとWSL版を行き来して使っていると、ふと「Windows側のセッションから、WSLにあるcronスクリプトを実行したい」という場面に出会います。私の環境では、Windows側をメインにしつつLinux向けツールや定時ジョブはWSL側に置く運用をしています。

ところが素直にやると事故ります。Windows側Claude Codeには、Windows形式パス（`C:\...`）とLinux形式パス（`/mnt/c/...`）を相互変換するpath-rewriteフックが入っており、これがコマンド内のパスらしき文字列を「よかれ」として勝手に書き換えてしまうのです。結果、file not foundになったり、意図しないディレクトリを操作されたりしました。

本記事では、**コマンドラインにパスを一切含めずにディスパッチする層（wslrun）**を1枚噛ませて、この問題を構造的に潰す設計をbash / Python双方のコード例で紹介します。

## 問題：path-rewriteフックはパス引数を標的にする

まず失敗例を見てみましょう。Windows側からWSLのスクリプトを呼ぶとき、Claude Codeは次のようなコマンドを組みます。

```bash
wsl.exe bash -lc "/path/to/cron/cleanup.sh --target /path/to/logs"
```

一見正しいのですが、path-rewriteフックはこのコマンドラインに登場するパス文字列を検知し、実行前に別形式へ書き換えます。スクリプト本体のパスも、引数の`--target`の値も、書き換え対象になり得ます。引数側が書き換わるのが特にたちが悪く、「cleanupしたつもりが別ディレクトリを見ていた」「チルダ展開の結果が変わりジョブが空振りした」といった、ログだけ見ると原因が分からない事故になりました。

フック側の除外設定で個別に対処する方法もありますが、マッチ条件はバージョンや設定で変わりうるため、設定依存の回避策は壊れやすいです。そこで発想を変えて、**そもそもコマンドラインにパスを載せなければ、書き換えようがない**という構造にしました。

## 設計：パス不含引数でディスパッチする層を噛ませる

wslrunは「ジョブ名＋パスを含まないkey=value引数」だけを受け取り、実際のスクリプトパスへの解決をWSL側内部で完結させるディスパッチャです。Claude Codeが発行するコマンドはこう変わります。

```bash
wsl.exe -e bash -lc "wslrun cleanup-logs days=7"
```

パスが1文字も無いので、path-rewriteフックには介入する余地がありません。ジョブ名からスクリプトを引く仕組みには2種類の実装を用意しました。

### bash版：ディレクトリをジョブテーブルにする

ジョブ名のバリデーションでパス区切り文字を排除するのが肝です。

```bash
#!/usr/bin/env bash
# wslrun: パス不含引数でWSL cronジョブへディスパッチする
set -euo pipefail

JOBS_DIR="${WSLRUN_JOBS_DIR:-/path/to/cron.d}"
job_name="$1"; shift

# ジョブ名は英数字・アンダースコア・ハイフンのみ許可(パス・メタ文字を排除)
if [[ ! "$job_name" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
  echo "invalid job name: $job_name" >&2
  exit 2
fi

job_script="$JOBS_DIR/$job_name.sh"
if [[ ! -f "$job_script" ]]; then
  echo "unknown job: $job_name" >&2
  exit 3
fi

exec bash "$job_script" "$@"
```

### Python版：JSONテーブル＋パスらしき引数の事前拒否

Python版では引数側の防御も強化し、`/`・`\`・`:`を含む値を受け取った時点で拒否します。ジョブ追加はテーブルに1行足すだけです。

```python
#!/usr/bin/env python3
"""wslrun: パス不含引数でWSL cronジョブへディスパッチする"""
import json
import re
import subprocess
import sys
from pathlib import Path

JOB_TABLE = Path("/path/to/wslrun/jobs.json")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: wslrun <job-name> [key=value ...]", file=sys.stderr)
        return 2

    job_name, args = sys.argv[1], sys.argv[2:]

    if not NAME_RE.match(job_name):
        print(f"invalid job name: {job_name}", file=sys.stderr)
        return 2

    # パスらしき引数は事前拒否(path-rewriteフックの標的にならないように)
    for a in args:
        if any(c in a for c in ("/", "\\", ":")):
            print(f"path-like argument rejected: {a}", file=sys.stderr)
            return 4

    jobs = json.loads(JOB_TABLE.read_text(encoding="utf-8"))
    if job_name not in jobs:
        print(f"unknown job: {job_name}", file=sys.stderr)
        return 3

    cmd = ["bash", jobs[job_name]["script"], *args]
    return subprocess.run(cmd).returncode

if __name__ == "__main__":
    sys.exit(main())
```

```json
{
  "sync-config":   { "script": "/path/to/cron/sync-config.sh" },
  "cleanup-logs":  { "script": "/path/to/cron/cleanup.sh" }
}
```

この設計には副次的な効果もあります。実行可能なスクリプトがテーブルに登録されたものだけ、つまり**ホワイトリスト方式**になるため、Claude Codeが意図しないコマンドを組み立ててしまうリスクも同時に下がります。

運用面では、共有ルール（CLAUDE.md）に「WSLのジョブは必ず `wslrun <ジョブ名>` 形式で呼び、パスを直書きしない」と1行書いておくだけで済みました。ルールを守らせる仕組みをプロンプト側に求めるより、コマンドの形自体で縛るほうが確実です。

## おわりに

Windows-WSL相互運用でのpath-rewriteフック問題は、フックと戦うのではなく「フックが介入する余地を構造的に消す」という方向で解決するのが頑健でした。ポイントは3つです。

1. コマンドラインにはジョブ名とkey=valueのみ（パスゼロ）
2. パス解決はWSL側のディスパッチャ内部で完結
3. ホワイトリスト方式で安全性も確保

ジョブの追加はテーブルに1行足すだけなので、運用コストもほぼゼロです。Windows版とWSL版を行き来して同じ事故に遭っている方は、ぜひこの「ディスパッチ層を1枚噛ませる」パターンを試してみてください。