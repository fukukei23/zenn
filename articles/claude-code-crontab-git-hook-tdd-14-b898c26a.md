---
title: "【Claude Code】crontab正典をgit管理する設計術：コミット漏れ検知hookをTDDで作る14テスト全記録"
emoji: "⏰"
type: "tech"
topics: ["ClaudeCode", "crontab", "TDD", "git管理", "hook"]
published: false
---

# はじめに

公務員からIT業界に転職して数年、私が最も「転職前との温差」を感じたのが **cronの運用** です。役所時代は紙の台帳でしたが、IT実務ではcrontabこそが本番インフラの心臓部。なのに多くの現場でcrontabは「個人のローカル設定」のまま、git管理から完全に漏れています。

実際に私の環境でも事故が起きました。**cronをcrontabに登録したのに、その定義を正典（設定の一次情報源）へコミットし忘れていた**のです。結果、正典に存在しない「ghost cron」が3件（id=27/28/29）も稼働していました。

本記事では、自分の設定管理用リポジトリ（claude-config）で実践している次の3点を紹介します。

1. crontabを「正典スクリプト」でgit管理する設計
2. コミット漏れを自動検知するhookを **TDDで14テスト書きながら作る** 手順
3. ghost cron問題の実際の解消記録

# 1. crontabを「正典」でgit管理する設計

設計の柱は **Single Source of Truth（正典パターン）** です。

- cronの定義はすべて `renew-crons.sh` というスクリプトに書く
- そのスクリプトを実行すると、定義がcrontabへ反映される
- crontabを直接編集することは禁止（正典を編集→反映が唯一の経路）

このルールを守ると、嬉しいことが3つあります。

- **変更がgit diffで見える**：誰がいつ何を変えたか履歴に残る
- **レビュー可能になる**：PRでcron変更を確認してから反映できる
- **環境の復元が楽**：新しいマシンでも正典を実行するだけで再現できる

ただし、この設計には天敵がいます。**「crontabへは反映したが、正典の変更をコミットし忘れた」** というパターンです。crontab側は最新・git側は古い、という齟齬が静かに蓄積していきます。そこで作ったのが検知hookです。

# 2. コミット漏れ検知hookをTDDで作る（14テスト）

作ったのは `crontab-ref-git-check.sh`。crontabの実行内容と、gitで管理している正典の内容を突合し、齟齪があれば警告します。**検知は雛形（bootstrap）として、チェック部自身を最初に正典として保存する** 作りにしました。

実際の実装はbashですが、ここでは概念をPythonで簡略化して示します。

```python
import re
import subprocess

CANONICAL = "/path/to/repo/crons/renew-crons.sh"

def fetch_live_crontab() -> str:
    """crontab -l で実運用の内容を取得。失敗時は例外で即死させる"""
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"crontab取得失敗: {proc.stderr.strip()}")
    return proc.stdout

def extract_ids(text: str) -> set[str]:
    """各定義の id=N タグを抽出して集合として返す"""
    return set(re.findall(r"id=(\d+)", text))

def check() -> int:
    live = extract_ids(fetch_live_crontab())
    with open(CANONICAL) as f:
        canonical = extract_ids(f.read())

    ghost = live - canonical      # crontabにあるのに正典にない＝コミット漏れ
    pending = canonical - live    # 正典にあるのに未反映

    for cron_id in sorted(ghost):
        print(f"ghost cron: id={cron_id} が正典に未定義（コミット漏れ）")
    for cron_id in sorted(pending):
        print(f"pending: id={cron_id} がcrontabへ未反映")
    return 1 if (ghost or pending) else 0
```

ここで最重要なのが `fetch_live_crontab` の returncode チェックです。最初の実装ではこれがなく、**crontabの取得に失敗すると空文字列が返り「差分ゼロ＝問題なし」と誤判定する偽陰性** を抱えていました。Claude Codeで複数モデルのレビューをループで回していたところ、この偽陰性がcriticalとして指摘され、修正に至りました。

テストはTDD（Red→Green→Refactor）で、合計14件を先に書きました。印象に残っているのは次の2件です。

- **T6（雛形）**：新規環境でチェック部自体がまだ正典に無い状態を想定。bootstrap動作を壊さないことを保証
- **T9（文言）**：テストを書き進める過程で、**本体（実装側）に警告文言の出力漏れがあること** が発覚。テストが実装のバグを先に見つけてくれる、TDDの価値を体感した瞬間でした

完成後は、日次で回っている `crontab-backup.sh` の中からsubshellで呼び出す形で組み込みました。検知に失敗してもwarnを記録するだけにして、バックアップ本体のexitコードは変えない——**検知はあくまで付加機能であり、本流を止めない** 設計です。

# 3. ghost cron 3件との対峙（id=27/28/29）

hookが完成すると、早速被害者（？）が見つかりました。id=27/28/29の3定義です。

- **id=27/28/29**：crontabには存在するのに正典に定義がなかった。過去に登録したベンチマーク用スクリプト等のコミット漏れでした。正典へ定義を追記し、スクリプト本体も一緒にコミットして解消
- **id=30/31**：逆パターン。正典の説明行が曖昧だったためghostと誤判定されていました。説明行を※注記形式に整理し、実体との対応タグを明記して解消
- **id=29**：システム側crontabで運用するものだったため、正典では `enabled=false` を付与して突合対象から分離

面白いのは、**検知器を丁寧に作ったおかげで、検証対象（正典）の不備まで洗い出された** 点です。hookが「正典の書き方の規約」を事実上強制するようになり、以後のghostは出ていません。

# おわりに

crontab衛生管理の3点セットをまとめます。

1. **正典パターン**：cron定義はgit管理されたスクリプトに集約し、直接編集を禁止する
2. **検知hook**：crontab実運用と正典の突合を自動化し、既存バックアップ処理に組み込む
3. **TDD**：検知器こそテストを書く価値が高い。偽陰性（静かに「問題なし」と言うバグ）はテストがないと絶対に気づけない

cronは「動いている間は誰も見ない」インフラです。だからこそ、正典という「見える場所」に置き、齟齪を機械が叫んでくれる仕組みが要ります。皆さんの環境の `crontab -l` も、一度正典と突合してみてはいかがでしょうか。意外なものが見つかるかもしれません。