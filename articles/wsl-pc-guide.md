---
title: "【初心者向け】スクリプトの可搬性完全ガイド：WSLユーザー名ハードコード去除で新PC移行をスムーズに"
emoji: "🚀"
type: "tech"
topics: ["Python", "WSL", "初心者向け", "環境構築"]
published: false
---

# はじめに

新しいPCを買ったり、職場のPCを買い替えたりしたとき、いつものように自分の作業環境（WSLなど）を構築し、GitHubから自分のスクリプトや設定ファイルを `git clone` してさあ動かそう！とした瞬間……

```bash
python /home/old_username/scripts/my_script.py
# => FileNotFoundError: [Errno 2] No such file or directory: '/home/old_username/...'
```

このようなエラーに出くわして憂鬱になった経験はありませんか？
「前のPCではちゃんと動いていたのに、なぜ？」

原因は明快で、**スクリプトや設定ファイルの中に「前のPCのユーザー名（パス）」が直接書き込まれてしまっている**からです。プログラミングの世界では、これを「ハードコード（直書き）」と呼びます。

本記事では、初心者の方でもすぐに実践できる「ユーザー名のハードコード去除」の具体的な方法を、PythonとBashスクリプトのコード例を交えてわかりやすく解説します。設定ファイルを少し工夫するだけで、新PCへの移行が驚くほどスムーズになります。

---

# なぜ「ユーザー名のハードコード」が問題になるのか？

LinuxやWSLの環境では、ユーザーのホームディレクトリは基本的に `/home/ユーザー名/` というパスになります。

もし、あなたのPCのユーザー名が `taro` だったとします。スクリプトを初めて書いたとき、つい以下のようにパスを直接書いてしまうことがあります。

```python
# 悪い例：ユーザー名がハードコードされている
log_file = "/home/taro/my_project/data/log.txt"
```

新PCでユーザー名を `jiro` にした場合、上記のスクリプトは `/home/taro/...` を探しに行ってしまい、ファイルが見つからずエラーになってしまいます。

「新しいPCに移行するたびに、すべてのファイル内の `taro` を `jiro` に一括置換すればいいじゃん」と思うかもしれませんが、これは非常に手間がかかりますし、修正し忘れによるバグの温床になります。

この問題を解決するには、**「特定のユーザー名に依存しない書き方」** をする必要があります。

---

# 解決策：環境変数と便利な関数でパスを一般化する

ユーザー名をハードコードせずにホームディレクトリを取得するには、使用する言語やツールが用意している「環境変数」や「組み込み関数」を利用します。

## 1. Bashスクリプトの場合：`$HOME` を使う

シェルスクリプト（.shファイル）を書く場合、`$HOME` という環境変数を使います。これは、現在ログインしているユーザーのホームディレクトリを自動的に返してくれる優れものです。

```bash
# 悪い例
SCRIPT_PATH="/home/taro/scripts/notify.sh"
CONFIG_PATH="/home/taro/.config/my_tool"

# 良い例：$HOME を使って可搬性を高める
SCRIPT_PATH="$HOME/scripts/notify.sh"
CONFIG_PATH="$HOME/.config/my_tool"
```

また、WindowsのPowerShellで書かれているスクリプトがある場合は、`$env:USERPROFILE` に置き換えることで同様にユーザー名の依存をなくすことができます。これだけで、どのPCに持っていっても正しいパスを参照できるようになります。

## 2. Pythonスクリプトの場合：`Path.expanduser()` を使う

Pythonでファイルパスを扱う際は、標準ライブラリの `pathlib` を使うのがモダンな書き方です。`Path` オブジェクトの `expanduser()` メソッドを使うと、パス文字列の中のチルダ（`~`）を自動的に現在のユーザーのホームディレクトリに展開してくれます。

```python
from pathlib import Path
import json

# 悪い例
# config_path = "/home/taro/config/settings.json"

# 良い例：チルダ (~) と expanduser() を組み合わせる
config_path = Path("~/.config/my_tool/settings.json").expanduser()

# ファイルの読み込みも安全に実行できる
if config_path.exists():
    with config_path.open('r') as f:
        settings = json.load(f)
    print("設定を読み込みました")
else:
    print("設定ファイルが見つかりません")
```

このように書き換えるだけで、`taro` のPCでも `jiro` のPCでも、さらにはMacや他のLinux環境でも全く同じコードで動くようになります。

---

# 設定ファイル（YAML/JSON）のパスも動的に解決しよう

ここまでスクリプトファイル本体の修正方法を見てきましたが、もう一つ見落としがちな罠があります。それは **`paths.yaml` や `config.json` などの設定ファイル** です。

設定ファイル内にログの出力先などを書く際も、ハードコードを避ける工夫が必要です。

## 設定ファイル側の工夫（チルダの活用）

設定ファイル（YAMLやJSON）の中では、直接 `expanduser()` のような関数を呼び出すことはできません。そこで、**パスの先頭にチルダ（`~`）を付けておく** というルールを採用します。

**`config/settings.yaml` の例:**
```yaml
# ログディレクトリの指定
# ~/ を先頭につけることで、「このPCのホームディレクトリ配下」という意味になる
logging:
  dir: "~/my_project/logs"
  level: "INFO"
```

## Python側で設定を読み込む際のベストプラクティス

設定ファイル内に `~` を書いておけば、あとはPython側でその設定ファイルを読み込む際に `expanduser()` を噛ませるだけで、安全に絶対パスへ変換できます。

```python
import yaml
from pathlib import Path

def setup_logging(config_file="config/settings.yaml"):
    # 設定ファイル自体もホームディレクトリ配下にあるかもしれないので展開
    config_path = Path(config_file).expanduser()
    
    with config_path.open('r') as f:
        config = yaml.safe_load(f)
    
    # 設定ファイルから取得したパス（~/my_project/logs）を展開
    log_dir_str = config['logging']['dir']
    log_dir = Path(log_dir_str).expanduser()
    
    # ディレクトリが存在しない場合は作成
    log_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"ログディレクトリを準備しました: {log_dir}")

setup_logging()
```

このような設計にしておけば、新PCに移行した際でも、Pythonスクリプトや設定ファイル群をそのままコピー（または `git clone`）するだけで、一切コードを書き換えることなくその日のうちに作業を再開できます。

---

# おわりに

新PC移行時の「スクリプトが動かない問題」は、ちょっとした意識づけで完全に防ぐことができます。

今回解説したポイントをまとめます。

1. **スクリプト内のユーザー名はハードコード（直書き）しない**
2. **Bashスクリプト** では `$HOME` 環境変数を使用する
3. **Pythonスクリプト** では `Pathlib` の `Path().expanduser()` を活用する
4. **YAMLやJSONなどの設定ファイル** では `~/` を用い、読み込み側のスクリプトで展開する

最初は少し面倒に感じるかもしれませんが、一度この書き方を癖づけておけば、PCを買い替えるたびに発生する無駄な修正作業から永遠に解放されます。「スクリプトの可搬性（どこでも動く性質）を高める」という観点は、実務においても非常に高く評価されるスキルです。

今回の記事を参考に、ぜひ皆さんの手元にあるスクリプトや設定ファイルを見直してみてください。未追跡だったスクリプトもGit管理下に置いて、いつでも安心して新環境へ飛び込める準備を整えましょう！