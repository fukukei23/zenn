---
title: "Claude CodeでAPIキーを漏らさない：権限ポップアップの「今後許可」が秘密を保存していた実録インシデント対応"
emoji: "🔐"
type: "tech"
topics: ["claude", "security", "api", "claudecode"]
published: true
---

## はじめに

Claude CodeのようなAIコーディングエージェントは便利ですが、**APIキーを間違えて会話やファイルに露出させるリスク**と常に隣り合わせです。

本記事の元になった事故では、APIキー入りコマンドが**なんと発覚まで約7週間（49日）、誰も気づかないまま設定ファイルに保存され続けていました**。しかも発覚後「ローカルだけだから大丈夫」と思っていたら、**自動同期スクリプト経由でGitHubまで到達していた**（混入から外部到達の発覚までは65日）という2幕構成でした。

本記事では、この実録インシデントを時系列で振り返りながら、Claude Code環境でAPIキーを守る**実践的な安全パターン**を解説します。AIコーディングエージェントを使うすべての人に通用する内容です。

> 📝 **注記**: 本記事は実録に基づく再構成です。日付の算出根拠は混入日=混入コミットの日付・発見日=調査記録の日付（いずれも当時の作業記録）です。フックのコード例は執筆時点（2026-10・Claude Code v2.1.x）の公式仕様に沿っています。バージョンにより保存形式やフック仕様が変わる可能性があるため、詳細は[公式ドキュメント](https://code.claude.com/docs/en/iam)で随時確認してください。

## インシデント実録：発覚まで49日気づかなかった露出

### タイムライン

```
2026-06-10  権限ポップアップで「今後許可」を選択
            → Discord BOTトークン生値入りのコマンド全文が
              settings.json の allow リストに永続化（この時点で混入）

2026-07-29  「フォルダ承認ポップアップが出なくなった」という
            一見無関係な不具合の調査中に発覚
            ① permissions.defaultMode=bypassPermissions が有効化されていた
            ② allow リスト4エントリにトークン生値が混入していた

2026-08-14  「remote無しのローカルgitだから外部漏洩ゼロ」という
            安全確認の前提が崩れる
            → 無加工cpするレガシー同期スクリプトが
              生値入りの副本を GitHub private repo まで運搬していた
```

### どうやって混入したのか（経路の核心）

問題のコマンドはこんな形でした:

```bash
# ❌ トークンをコマンドライン引数に直接書いている
curl -H "Authorization: Bot MTIzNDU2Nzg..." https://discord.com/api/...
```

ここで重要なのは、**このコマンドがどこに保存されるか**です。Claude Codeは権限ポップアップで「今後許可（Always allow）」を選ぶと、**コマンド全文を `settings.json` の allow リストにそのまま永続化**します。トークンも「コマンドの一部」として、丸ごと保存されます。

```
権限ポップアップ「今後許可」
  └─> settings.json の permissions.allow に、例えば次のようなエントリが
      トークン生値入りのまま保存される（値はダミー・構造は当時の観測に基づく）:

      "permissions": {
        "allow": [
          "Bash(curl -H \"Authorization: Bot MTIzNDU2Nzg...\" https://discord.com/api/*)"
        ]
      }
```

つまり、**AIエージェントへの「便利な権限設定」が、そのままシークレットの保存場所になっていた**わけです。設定ファイルをgit管理しているなら、これはそのままコミット対象になります。

なお、**秘密をコマンド引数に書くこと自体が第一の不良実践**です（シェル履歴・プロセスリストに残る）。本節で着目してほしいのは、その上で「便利な権限設定」が事故を**49日間の長期潜伏**に発展させた二次被害構造の方です。

### なぜ49日気づかなかったのか

1. 混入時点では異常がない（コマンドは正常に動く）
2. 設定ファイルの中身を定期的に確認する運用がなかった
3. 「ローカル限定のgit repo・remote無し」だから外部に出ない、という安心感

3つ目の安心感は後述の第2幕（GitHub到達）で崩れました。

## AIエージェント環境の4つの露出経路

実録で踏んだ経路を含め、見落としやすい4経路を整理します。

### 経路1: ファイル読み取り

```bash
# ❌ Claude Codeが実行するとAPIキーが会話（コンテキスト）に表示される
cat ~/.claude/settings.json
```

AIエージェントは「確認のためにファイルを開く」のが日常動作です。設定ファイルに秘密があれば、それだけで会話ログに載ります。

### 経路2: 環境変数の表示

```bash
# ❌ 全環境変数を表示
env | grep API
```

### 経路3: jqで設定ファイルをダンプ

```bash
# ❌ 「jqで確認してください」とAIに言われるまま実行
jq . ~/.claude/settings.json  # APIキーが含まれる
```

### 経路4: 権限ポップアップの「今後許可」（本事故の経路）

```text
# ❌ 秘密入りコマンドをポップアップで「今後許可」
→ コマンド全文（秘密を含む）が settings.json に永続化される
→ 以後、設定ファイルを見るすべての人・AI・ツールが秘密に触れられる
```

この経路の厄介なところは、**その場では何も起きない**ことです。混入した瞬間に異常は一切なく、「気づくきっかけ」すら別の不具合調査である必要がありました。

## 根本対策：シークレットはコマンド引数に書かない

経路4を物理的に潰すルールは1つだけです。

### ❌ 悪い例: 秘密をコマンドライン引数に直接書く

```bash
curl -H "Authorization: Bot MTIzNDU2Nzg..." https://discord.com/api/...
```

コマンドライン引数は、シェル履歴・権限allowリスト・プロセスリスト（`ps`）など、**複数の場所に平文で残る**形です。

### ✅ 良い例: 環境変数で渡す

```bash
# 秘密は ~/.secrets.env に一元管理し、行頭に export を付けておく
# export DISCORD_BOT_TOKEN=xxx

# 使う時は source で読み込んで変数参照
source ~/.secrets.env && curl -H "Authorization: Bot $DISCORD_BOT_TOKEN" https://discord.com/api/...
```

こうすれば、allow リストに永続化されるコマンドには **変数名しか含まれません**。権限を「今後許可」しても安全です（このコマンドが後で再利用されても、変数が未設定なら失敗するだけで値は出ません）。より厳格には、ヘッダをファイル経由で渡す方法もあります:

```bash
# curl -K でヘッダを設定ファイル経由にする（プロセス引数にもコマンド文字列にも値が出ない）
printf 'header = "Authorization: Bot %s"\n' "$DISCORD_BOT_TOKEN" > /tmp/.hdr && curl -K /tmp/.hdr https://discord.com/api/... && rm /tmp/.hdr
```

> ⚠️ **限界の明示**: シェルが展開した後の値は `/proc/<PID>/cmdline`（`ps` で見えるプロセス引数）には現れます。より厳格にしたい場合は、ヘッダを設定ファイル経由で渡す `curl -K` や標準入力渡しを使ってください。

> 💡 ポイント: 「秘密の値」がどこにも保存されない形にするのが理想ですが、現実には「保存される場所を1つ（~/.secrets.env）に限定する」のが運用として強力です。

## 安全パターン（確認作業の受け答え方）

AIエージェントに「APIキー設定されてる？」と聞かれた時の安全な確認方法です。

### APIキーの存在確認

```bash
# ✅ キーが設定されているかだけ確認
[ -n "$DISCORD_BOT_TOKEN" ] && echo "set" || echo "unset"
```

### キー名一覧

```bash
# ✅ キー名だけ表示、値は伏せ
grep -E "^(export )?[A-Z_]+=" ~/.secrets.env | sed "s/=.*/=<REDACTED>/"
```

### 長さ確認

```bash
# ✅ 長さだけ確認（値の形が変わっていないかの目安）
echo "len=${#DISCORD_BOT_TOKEN}"
```

**キーの「値」を会話・ファイル・コミットに書かない。キー名はOK、値はNG** —— これが唯一の安全なルールです。

## 多層防御の実装

### 第1層: PreToolUseフック（技術的強制）

「運用で気をつける」は人は忘れるので、コマンド実行**前**にフックでチェックします。Claude Codeのフックは **stdin でイベントJSONを受け取り、`exit 2` でコマンド実行をブロック**する仕様です（[公式ドキュメント](https://code.claude.com/docs/en/hooks)）。フックが受け取るイベントは例えば次のような形です:

```json
{ "tool_name": "Bash", "tool_input": { "command": "cat ~/.secrets.env" } }
```

その仕様に沿った動作例（cat系読み取りブロック+jqのホワイトリスト判定を統合）:

```python
#!/usr/bin/env python3
# check-command-safety.py — secrets系ファイルの読み取りをブロックするPreToolUseフック
import json, re, sys

event = json.load(sys.stdin)
cmd = event.get("tool_input", {}).get("command", "")

READERS = r"\b(cat|head|tail|less|more|bat)\b"
TARGETS = [r"\.env", r"credentials", r"secrets"]  # 派生ファイル(.env.backup等)も拾う
ALLOWED_JQ_QUERIES = {".statusLine", ".model", ".permissions"}  # jqは完全一致ホワイトリスト

blocked, reason = False, ""
if re.search(r"\bjq\b", cmd):
    m = re.search(r"jq\s+'?([^'\s]+)'?", cmd)
    if not (m and m.group(1) in ALLOWED_JQ_QUERIES):
        blocked, reason = True, "jqは許可クエリの完全一致のみ実行可"
elif re.search(READERS, cmd) and any(re.search(t, cmd) for t in TARGETS):
    blocked, reason = True, "secrets系ファイルの直接読み取り"

if blocked:
    print(reason + "\nキー名一覧の確認は: grep -E '^(export )?[A-Z_]+=' ~/.secrets.env | sed 's/=.*/=<REDACTED>/'",
          file=sys.stderr)
    sys.exit(2)  # Claude Codeでは exit 2 = ツール実行のブロック
sys.exit(0)
```

`settings.json` への登録例（`Bash` ツールの実行前に呼ばれる）:

```json
{
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    { "type": "command", "command": "python3 ~/.claude/scripts/hooks/check-command-safety.py" }
                ]
            }
        ]
    }
}
```

導入は3ステップです（macOS/Linux・POSIXシェル前提）:

```bash
mkdir -p ~/.claude/scripts/hooks
# 上記スクリプトを ~/.claude/scripts/hooks/check-command-safety.py として保存
chmod +x ~/.claude/scripts/hooks/check-command-safety.py
# 動作確認（"2" が返ればブロック動作OK）
echo '{"tool_input":{"command":"cat ~/.secrets.env"}}' | python3 ~/.claude/scripts/hooks/check-command-safety.py; echo "exit=$?"
```

> ⚠️ **このフックの限界**: 正規表現による判定は、`alias cat='bat'`・シェル関数・`awk`/`sed` での読み取り等で回避できます。これは「うっかりミス」を防ぐ**最前線**であって最終防衛線ではありません。最終防衛線は第3層（secrets.envへの集約+パーミッション絞り）です。

### 第2層: jq ホワイトリスト（ギャップ修正）

初期実装では `jq` がブロック対象外でした。cat系を塞いでも `jq . settings.json` で全部ダンプできてしまう——いわゆる**抜け穴**です。

ここで注意したいのは設計方式です。**ブラックリスト（「このクエリは禁止」の列挙）は列挙漏れの抜け穴を無限に生む**ので、**ホワイトリスト（許可クエリの完全一致以外は全部ブロック）**に反転させます。上のフックコードの `ALLOWED_JQ_QUERIES` がその実装で、`jq .`（全ダンプ）はブロックされ、`jq .model`（特定キー）だけが通ります。

### 第3層: ~/.secrets.env への集約

```bash
# ~/.secrets.env（単一ファイルに集約・git管理外）
export MINIMAX_API_KEY=xxx
export DISCORD_BOT_TOKEN=xxx
export GITHUB_TOKEN=xxx

# 各プロジェクトの.envには書かない（.env.example だけ残す）
# 必要に応じて source ~/.secrets.env で注入
```

設定ファイル側は値を書かず、`${VAR}` 展開記法で環境変数を参照します:

```json
{
    "mcpServers": {
        "brave-search": {
            "env": {
                "BRAVE_API_KEY": "${BRAVE_API_KEY}"
            }
        }
    }
}
```

`~/.secrets.env` 自体は秘密を含むため、パーミッションを絞っておきます:

```bash
chmod 600 ~/.secrets.env   # 自分以外読めない
```

### 第4層（追加）: 同期スクリプトの監査

第2幕（GitHub到達）の教訓です。本事故の到達メカニズムを具体的に書くと:

```text
SessionStart/Stop hook の同期スクリプトが
  設定ファイルの副本を知識ベースリポジトリへ「無加工のままcp」
    → そのリポジトリの自動commit+pushが生値入りの副本を
      GitHub private リポジトリまで運搬
```

「正しいマスク経路」と「無加工cpのレガシー経路」が二重に並存しており、後者が生値を運んでいました。監査の観点は:

```text
チェックリスト:
□ 設定ファイルをコピーするスクリプトは全て列挙したか
□ それぞれマスク処理を経由しているか（無加工cp が無いか）
□ git管理下の副本に生値が無いか（下記コマンドで定期確認）

# 現在の作業ツリー（チェックアウト中のファイル）を点検
git grep -l "API_KEY" -- '*.json'
# 過去コミット（履歴）まで調べるなら git grep では見えないのでこちら
git log --all -S "API_KEY" --oneline
```

※ `git grep` は現在の作業ツリーが対象で履歴は見ません。履歴は `git log -S`（ピックアップ文字列検索）を使います。またキー名検索は、値がbase64化・リネームされた副本は検出できない点にも限界があります。

## インシデント対応フロー

万が一APIキーが露出した場合の対応:

```
1. 可能なら悪用痕跡を保全（サービス側の監査ログ・アクセス履歴を確認・保存してから次へ）
2. 露出したキーをローテーション（新しいキーを発行・旧キーを失効させる）
3. settings.json の allow リストを点検・混入エントリを削除
4. git履歴に生値が残っていないか確認
   - remoteへpush済みなら到達範囲を調査（privateリポジトリでも履歴は残ります。GitHubの
     secret scanning alertはプラン・設定に依存するため自分のリポジトリ設定を確認。
     履歴から消すなら git filter-repo / BFG を検討・手順は
     [GitHub公式ドキュメント](https://docs.github.com/ja/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)参照・必要ならGitHub Supportへ報告）
5. ~/.secrets.env を更新（値は記載しない形でインシデント記録）
6. 原因を分析してフック・ルールを追加（同じ経路の再発を潰す）
```

最初に「会話を終了させる」と説明しがちですが、**露出済みのキーの寿命はローテーションで止める**のが先です。会話ログは削除しても、allowリストやgit履歴に残った値は消えません。

## まとめ

| 教訓 | 内容 |
|------|------|
| 「今後許可」はコマンド全文を保存する | 秘密をコマンド引数に書かない＝allow永続化しても安全 |
| 気づかないうちに混入している | 設定ファイルの定期点検（`git log -S` やキー名一覧の目視）を運用に入れる |
| 「ローカルだけ」の安心は崩れる | 副本・同期スクリプト経由で外部（GitHub等）へ到達しうる |
| 露出後はローテーション最優先 | 消せない場所に残った値の寿命は、キーの失効で止める |

**APIキーの値を絶対に会話・ファイル・コマンド引数に書かない**——この1行を、AIコーディングエージェントを使い始めた日に設定しておくのが、本記事からの一番の持ち帰りです。

## 関連記事

- [AIエージェント開発環境に秘密情報流出ゲートを自作して2週間運用したら誤警報ゼロだった話](https://zenn.dev/fukukei23/articles/secret-leak-gate-ai-agent-env-2weeks) — 本記事の多層防御をCI/フックで自動化した続編
- [Claude Code設定の3層設計 — CLAUDE.mdをどう分割するか](https://zenn.dev/fukukei23/articles/claude-code-claude-md-3-layer-design) — グローバル/プロジェクト/ディレクトリの使い分け

---

*この記事はClaude Codeと一緒に書きました。*
