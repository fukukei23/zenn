---
title: "【初心者向け】マルチLLMレビューでCLI安全性を底上げ：sync-from-ssot.shの5欠陥修正実例"
emoji: "🛡️"
type: "tech"
topics: ["Python", "ClaudeCode", "セキュリティ", "初心者向け", "コードレビュー"]
published: false
---

# はじめに

私は自分のリポジトリ **ssot-guide** で、Obsidianのメモ（SSOT: Single Source of Truth）をGitHub Pages向けに毎日同期する `sync-from-ssot.sh` というシェルスクリプトを運用しています。同期履歴を見ると、このスクリプトはほぼ毎日自動実行されており、**止まるとドキュメントが更新されない**重要な部品です。

しかし「動いているからOK」と放置していた結果、ある日ローカルのファイルが意図せず消える事故が起きかけました。そこで取り入れたのが **マルチLLMレビュー** です。複数のLLMに同じスクリプトを見せて、指摘の重なり方で欠陥の優先度を決めるという手法で、最終的に **5件の欠陥（C-1/C-2/M-1/M-2/M-3）** を修正できました。この記事では、その流れを「レビューフロー → 欠陥パターン → 回帰テスト」の3軸で紹介します。

# 1. マルチLLMレビューのフロー

単一のLLMレビューでも効果はありますが、1つのモデルには得意・不得意の偏りがあります。そこで私は次のようなフローで回しました。

1. **同じプロンプトを2〜3種類のLLMに投入**
   「このシェルスクリプトを安全性の観点でレビューし、指摘を重大度つきで列挙してください」という指示を、モデルを変えて実行します。
2. **指摘を1つのリストにマージ**
   複数モデルから挙がった指摘を重複ごとまとめます。
3. **優先度を決める**
   - 複数モデルが一致して指摘 → **C（Critical）**
   - 1モデルのみだが影響が大きい → **M（Major）**
4. **人間が最終判断**
   誤検知（この運用では起こり得ないパターンなど）は捨てます。LLMの指摘は「候補」であって「結論」ではありません。

今回の結果は C-1/C-2 の2件、M-1/M-2/M-3 の3件でした。

# 2. 見つかった5つの欠陥パターン

どれもシェルスクリプトで频出する定番パターンです。Before/Afterで示します。

## C-1: クォートなしの変数展開とrmの組み合わせ

```bash
# Before: スペース入りのパスで単語分割が起き、誤削除の危険
rm -rf $SYNC_DIR/sub

# After: クォート + 空変数なら即エラーで停止
rm -rf -- "${SYNC_DIR:?SYNC_DIR is unset}/sub"
```

`:?` を付けると変数が空のときスクリプトが停止します。`rm -rf` の引数では特に重要です。

## C-2: エラー時に処理が継続してしまう

```bash
# Before: 先頭におまじなし
#!/bin/bash

# After: 失敗したら即停止
#!/bin/bash
set -euo pipefail
```

`-e`（エラーで停止）、`-u`（未定義変数で停止）、`-o pipefail`（パイプ内の失敗を検知）の3点セットです。

## M-1: 固定パスの一時ファイル

```bash
# Before: 固定パスは衝突・シンボリックリンク攻撃の恐れ
TMPFILE=/tmp/sync.tmp

# After: mktempで一意なファイルを作り、EXITで必ず削除
TMPFILE=$(mktemp)
trap 'rm -f -- "$TMPFILE"' EXIT
```

## M-2: パイプでエラーが握りつぶされる

```bash
# Before: curlが失敗しても空ファイルができてしまう
curl -s "$SRC_URL" | jq . > out.json

# After: -fでHTTPエラーを検知し、一度ファイルへ受信
curl -sSfL "$SRC_URL" -o "$TMPFILE"
jq . "$TMPFILE" > out.json
```

## M-3: バックアップなしの上書きコピー

```bash
# Before
cp -r ssot/* guide/

# After: バックアップを残しつつ同期
rsync -a --backup --suffix=".bak.$(date +%s)" ssot/ guide/
```

この5件を **1コミットにまとめて** コミットメッセージに `fix: sync-from-ssot.sh 安全性改修（マルチLLMレビュー反映・C-1/C-2/M-1/M-2/M-3）` と欠陥IDを残しました。後から履歴を追跡しやすくなります。

# 3. 回帰テストで成果を固定する

修正しても、将来の変更で壊れては意味がありません。そこでPython + pytestで回帰テストを書きました。

```python
import subprocess
from pathlib import Path

SCRIPT = "/path/to/sync-from-ssot.sh"

def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
    )

def test_c2_stop_on_error():
    """C-2: 存在しないパス指定で非零exitすること"""
    result = run_script("/path/to/nonexistent")
    assert result.returncode != 0

def test_m1_no_leftover_tmp(tmp_path: Path):
    """M-1: 実行後に一時ファイルが残らないこと"""
    run_script(str(tmp_path))
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
```

ポイントは **欠陥IDをテスト名に紐付ける** ことです。「なぜこのテストがあるのか」がコミットメッセージと対応し、レビュー時の説明コストが激減します。CIに組み込めば、毎日の同期前に自動で確認できます。

# おわりに

マルチLLMレビューの本質は「**1つのLLMの見落としを、別のLLMの指摘で補う**」ことです。今回見つかった5件はいずれも定番パターンでしたが、自分の目では半年間気づけませんでした。

初心者の方への要点をまとめます。

- シェルスクリプトは `set -euo pipefail` とクォートから見直すだけで事故は大幅に減る
- LLMレビューは複数モデルで実施し、人間が最終判断する
- 修正は欠陥IDつきで1コミットにまとめ、回帰テストで守る

CLIツールは「動いている」ように見えても危険を抱えています。まず1つのスクリプトにこのフローを試してみてはいかがでしょうか。