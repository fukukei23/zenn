---
title: "【Claude Code】環境変数のWindows-WSL不伝播問題をargv明示渡しで解決する実装例"
emoji: "🔧"
type: "tech"
topics: ["ClaudeCode", "WSL", "Windows", "Python"]
published: false
---

## はじめに

Claude CodeをWSL上で使いつつ、hooks経由で自作スクリプトを回す運用をしています。ある日、「WSL側のシェルから直接実行すると問題なく動くのに、Windows側からフック経由で呼ぶとだけSID（セッションID）が空になる」という現象に遭遇しました。

結論から言うと、原因は**環境変数がWindowsとWSLのプロセス境界を越えて伝播しない**こと。そして解決は「環境変数で暗黙に渡す」のをやめて、`--sid` というコマンドライン引数（argv）で明示的に渡す設計への変更でした。

この記事では、問題の構造と修正の具体コード、そして「なぜargvに寄せたのか」を解説します。

## 起こっていたこと： .envはプロセス境界を越えない

まず前提として、Claude Codeのhooksは設定によってWindows側のプロセスから起動されることがあります。一方でスクリプト本体や`.env`ファイルはWSL側に置いてある――こういう構成です。

環境変数は「プロセスを起動した親から子へ」受け継がれる仕組みです。WSLのbashで`.env`を読み込んでexportしていれば、そのbashから起動したスクリプトには変数が見えます。ところがWindows側プロセス経由で起動される場合、WSL側でexportした値は（WSLENVなどの明示的な橋渡し設定がない限り）届きません。

- WSLのbashから実行： `.env` → export → `os.environ` で読める ✅
- Windows側からフック経由で実行： 変数が未定義のまま起動 ❌

たちが悪いのは「エラーで落ちてくれればまだマシ」な点です。`os.environ.get("SID", "")` のような取得の仕方をしていると、空文字のまま処理が進み、ログのセッション紐付けだけが静かに壊れます。実際、自分の環境ではプロキシログにセッション単位のタグを付ける仕組みがあり、タグだけ欠けたログが量産されてから問題に気づきました。

## 解決： SIDをargvで明示渡しする

修正方針はシンプルです。「SIDはスクリプト側で環境変数から拾う」を「呼び出し元が `--sid` で渡す」に反転させます。

修正前：

```python
import os

def main() -> None:
    sid = os.environ.get("CLAUDE_SESSION_ID", "")
    if not sid:
        # Windows側から呼ぶと空文字のまま処理が進んでしまう
        pass
    ...
```

修正後：

```python
import argparse
import sys

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="検知対象の解決")
    parser.add_argument(
        "--sid",
        required=True,
        help="セッションID（呼び出し元が明示的に渡す）",
    )
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sid = args.sid  # 以降は sid を信じて使える
    ...
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

ポイントは2つです。

1. **`required=True` で渡し忘れを即検知**： 未指定なら起動直後に引数エラーで落ちます（fail fast）。空文字で黙って進むバグより、はるかに調査が楽です。
2. **`argv` 引数でテスト可能に**： `parse_args(["--sid", "test123"])` のようにリストを渡せるので、単体テストで環境変数を汚す必要がありません。

呼び出し側はこう変わります。WSL側のラッパースクリプトで環境変数を拾い、argvに変換して渡します。

```bash
#!/usr/bin/env bash
# SIDの供給源は呼び出し元の責務。スクリプト本体はOS差異を知らない
python /path/to/detect-targets.py --sid "${CLAUDE_SESSION_ID:?SIDが未設定}"
```

`${VAR:?message}` は、変数が空なら即エラーで停止するbashの記法です。「どこからSIDを持ってくるか」が呼び出し元に集約され、スクリプト本体はWindowsから呼ばれてもWSLから呼ばれても同じインターフェースで動くようになりました。

## なぜ環境変数ではなくargvなのか

最後に設計判断の理由を整理します。

- **依存が見た目に現れる**: 環境変数は「暗黙の依存」で、動く環境と動かない環境の差がコードから読み取れません。argvなら呼び出し行を見るだけで依存が分かります。
- **伝播経路の管理コストを削減できる**: Windows-WSL間にはWSLENVという橋渡し手段もありますが、呼び出し経路ごとの挙動差を検証・維持するコストがかかります。argvはプロセス起動の引数なので、経路が何であれ必ず届きます。
- **将来の変更に強い**: 「フックの起動元が増える」「cronからも呼びたい」といった変更が起きても、スクリプト側は無修正で済みます。

## おわりに

環境変数は便利ですが、プロセス境界・OS境界を越える場面では「届かないかもしれないもの」として扱うのが安全です。特にhooksのように「どの環境から起動されるかを完全には制御できない」実行形態では、インターフェースをargvに寄せるだけで問題の多くを排除できます。

「WSLでは動くのにWindowsで動かない」に悩んだら、まず環境変数の伝播経路を疑ってみてください。その上での解決策として、この記事のargv明示渡しが参考になれば幸いです。