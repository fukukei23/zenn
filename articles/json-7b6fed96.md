---
title: "【初心者向け】壊れたJSONで朝のセッション起動を守る：例外耐性設計の具体例"
emoji: "🛡️"
type: "tech"
topics: ["Python", "Claude Code", "JSON", "例外処理", "初心者向け"]
published: false
---

## はじめに

朝イチで自作CLIを起動したら、いきなりtracebackで落ちた——そんな経験はありませんか。

私は自分のClaude Code環境を管理するCLIツールを持っていて、起動時にJSON形式の状態ファイルから「未読の作業候補」を読んで一覧表示するようにしていました。ある朝、このJSONファイルが壊れていたせいでコマンド全体が異常終了し、本来のメイン機能であるセッション再開まで使えなくなってしまったのです。

この記事では、そのときに追加した例外耐性の実例をベースに、次のことを初心者向けに解説します。

- なぜ「1個のJSONが壊れただけ」でCLI全体が落ちるのか
- try/except とフォールバック（代替値）の具体的な書き方
- 「朝の一発目で困らない」CLI運用の心得

## 何が起きたか：壊れたJSONで朝の起動が止まる

問題のコマンドは、起動時に次のような処理をしていました。

```python
import json

def load_pending_jobs(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # ここで落ちる
```

一見なんの変哲もないコードですが、JSONが壊れていると `json.JSONDecodeError` が送出されます。そして例外を誰も捕捉しないまま呼び出し元へ伝播し、最終的にコマンド全体が異常終了します。JSONが壊れる原因は日常的にあります。

- 別プロセスが書き込み中の途中の状態を読んでしまった
- 手動で編集していてカンマや括弧を忘れた
- ディスクフルや強制終了で、ファイルが途中までしか書かれていない

モノとしては「あると便利なおまけ表示」だったのに、その読み込みに失敗しただけでメイン機能が死ぬのは本末転倒です。しかも朝の一発目がこれだと、その日の最初の10分が復旧作業に溶けてしまいます。

## 例外耐性の入れ方：try/exceptとフォールバック

修正の方針はシンプルで、次の3点です。

1. 読み込み箇所を try/except で囲む
2. 失敗したら安全なデフォルト値にフォールバックする
3. サイレントに握りつぶさず、警告を残す

実際のコードはこうなりました。

```python
import json
import logging

logger = logging.getLogger(__name__)

def load_pending_jobs(path, default=None):
    if default is None:
        default = []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default  # 初回起動など「まだ無い」のは正常
    except json.JSONDecodeError as e:
        logger.warning("候補ファイルが破損(%s)。空扱いで続行します", e)
        return default  # 壊れても空リストで続行
    except OSError as e:
        logger.warning("候補ファイルの読み込み失敗: %s", e)
        return default
```

表示側も「0件なら何も出さない」ではなく、状況がわかる一文を出します。

```python
jobs = load_pending_jobs("/path/to/pending-jobs.json")
if jobs:
    for job in jobs:
        print(f"- {job['title']}")
else:
    print("(未読候補なし、または候補ファイルを読めませんでした)")
```

初心者が押さえたいポイントは3つです。

- **例外は狭く捕捉する**： `except Exception` や裸の `except:` は `KeyboardInterrupt`（Ctrl+C）まで飲み込むので危険です。ここでは想定できる3種類だけを、狭いものから順に明示します
- **フォールバック値は「その機能にとって安全な値」**： おまけ表示なら空リストで十分です。設定ファイルなら、前回の健全な値のコピーなどを選びます
- **警告ログを残す**： 握りつぶすと「いつの間にか表示が消えていた」ことに気づけません。劣化した事実は必ず記録します

## 設計の心得：壊れても死なない・壊れたら再生できる

今回の修正で一番効いた考え方は、**「表示は劣化しても本体は生かす」**という割り切りです。未読候補が一時的に見えなくても、セッション再開という本体が動けば業務は止まりません。逆に、本体が動かなければ候補一覧が完璧でも意味がありません。

あわせて効果的だったのが、**壊れたファイルが次回の書き込みで自然に上書きされる設計**にしておくことです。候補ファイルは定期実行ジョブが再生成するため、壊れてもしばらく経てば自動復旧します。手動復旧の手順書が要らないのが強みです。

さらに書き込み側を「一時ファイルに書いてからリネーム」にすると、そもそも壊れにくくなり、読み込み側の防御と二重の保険になります。

```python
import json
import os
import tempfile

def save_jobs(path, jobs):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # アトミックに差し替え
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
```

`os.replace` による差し替えは一瞬で完了するため、読み手が「書きかけの中途半端なファイル」を見る可能性がほぼゼロになります。

## おわりに

今回の修正は実質10行ほどの変更でしたが、「朝の一発目で死なない」という体感は劇的に変わりました。JSONを読むCLIを書くときは、次の4つを思い出してもらえたら嬉しいです。

- 想定される例外を明示的に捕捉する
- 意味のあるフォールバック値を返す
- 警告を残して握りつぶさない
- 書き込みはアトミックに行う

小さな防御の積み重ねが、「安心して毎朝叩けるCLI」を作ります。皆さんのツールも、壊れたJSONくらいでは止まらない作りにしていきましょう。