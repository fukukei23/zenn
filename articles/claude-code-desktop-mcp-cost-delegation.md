---
title: "Claude Code Desktop版、SonnetのままGLM/MiniMaxにMCP経由で作業を逃がしてコストを抑える話"
emoji: "🔀"
type: "tech"
topics: ["claudecode", "mcp", "llm", "コスト最適化", "glm"]
published: false
---

## はじめに

「Claude CodeのCLI版はGLMに置き換えてコストを下げた」という話は以前書きました。では **Desktop版（Windowsアプリ）はどうしているのか？** 実はこちらはCLI版とまったく違うアプローチを取っています。

結論から言うと:

> **Desktop版はSonnetを動かしたまま、MCP経由でGLM/MiniMaxに「作業の一部」を委譲してコストを抑えている**

この記事では、なぜそうなっているのか、CLI版と何が違うのか、そして実際にハマった「設定したのに繋がらない」問題の顛末まで書きます。

## 結論: 環境によって「節約の仕組み」がまるで違う

| | WSL CLI版 | Windows Desktop版 |
|---|---|---|
| **本体（ベースモデル）** | GLM-5.1（プロキシ経由でZAI APIに接続） | 本物のSonnet（Anthropic OAuth直結） |
| **節約の仕組み** | エンドポイント自体をGLMに向け替える | SonnetからMCP経由でGLM/MiniMaxに委譲 |
| **GLMの位置づけ** | 本体そのもの | 外部ツール（MCPサーバー） |
| **MCPとして意味を持つもの** | MiniMax（GLM自体は二重呼び出しになるため使わない） | GLM・MiniMax両方 |

同じ「GLM」「MiniMax」という名前が出てきても、CLI版とDesktop版では **役割がまったく別物** です。これを混同すると、設定をいくら見直しても「なぜか繋がらない」「なぜか節約できていない」という沼にハマります（実際にハマりました）。

## なぜこの違いが生まれるのか

### CLI版: エンドポイントを丸ごと差し替えられる

WSL CLI版は、Claude Code自体が読みにいく `ANTHROPIC_BASE_URL` という設定を書き換えるだけで、通信先をAnthropic以外（Z.AI＝GLM）に丸ごと向けることができます。これだけで **Claude Codeという皮を被ったGLM** として動かせます。

私の場合はそこにもう一段、レート制限対策のローカルプロキシ（`localhost:8787`）を挟んでいますが、これは「あると便利な追加レイヤー」であって必須ではありません。`ANTHROPIC_BASE_URL` を直接Z.AIのエンドポイントに向けるだけでもGLM化は成立します。

```
[最小構成]   Claude Code CLI → ANTHROPIC_BASE_URLの書き換え → ZAI API（GLM）

[私の構成]   Claude Code CLI → localhost:8787（プロキシ・任意）→ ZAI API（GLM）
                                                            └ レート制限時 → MiniMax（自動フォールバック）
```

どちらの構成でも本質は同じで、GLMは「呼び出す外部ツール」ではなく「Claude Codeの正体そのもの」になります。なのでわざわざMCP経由でGLMをもう一度呼び出すと、GLMがGLMを呼ぶという二重構造になってしまい、無意味です（実際、CLAUDE.mdにも「外部LLMの呼び出しは不要・不可」と明記してあります）。

一方MiniMaxは、①（プロキシを使っている場合の）レート制限フォールバック先、②MCP経由で明示的に呼び出すツール、という**2つの役割**を持てます。CLI版でMCPとして実用上意味があるのはMiniMaxの方だけ、というのがポイントです。

### Desktop版: エンドポイントを差し替えられない

Windows版のDesktopアプリ（特にMicrosoft Store版）は、CLIのような環境変数の書き換えができず、**Sonnet固定**で動きます。Sonnetは高品質ですが、当然コストも高い。

そこで使うのが **MCP（Model Context Protocol）** です。MCPサーバーとしてGLM・MiniMaxを呼び出し口として登録しておけば、Sonnetが「この作業はGLMに投げよう」「これはMiniMaxで」と判断して委譲できます。

```
Claude Code Desktop（Sonnet固定）→ glm MCP ────→ GLM
                                  → minimax MCP → MiniMax
```

つまりDesktop版では「本体はSonnetのまま、重い・大量・定型的な作業だけを安いLLMに外注する」という発想です。CLI版のような「丸ごと置き換え」ではなく、「部分的な委譲」によるコスト最適化、という違いがあります。

## 自作MCPサーバーの中身

GLM/MiniMaxをMCPツールとして使うために、サードパーティのnpmパッケージではなく **公式APIを直接叩く自作のMCPサーバー** をPythonで書いています。理由は、得体の知れない外部パッケージにAPIキーを渡したくなかったからです（実際、後述する動画生成MCPの選定でもこの判断が活きました）。

仕組みはシンプルで、JSON-RPC 2.0のstdioサーバーを素のPython（`urllib`のみ、SDK不使用）で実装しています:

```python
# 受信したJSON-RPCリクエストをそのまま処理するループ
for line in sys.stdin:
    req = json.loads(line.strip())
    response = handle_request(req)   # initialize / tools/list / tools/call を分岐
    if response:
        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()
```

`tools/call` が来たらAPIキーを `~/.secrets.env` から読み込み、GLMやMiniMaxの公式エンドポイントにリクエストを投げて結果を返すだけ。100〜200行程度で十分動きます。

## ハマった話: 「設定したのに繋がらない」の正体

ここからは実際にやらかした話です。新しいMCPサーバー（MiniMax公式の動画生成MCP）を追加しようとしたのですが、何度設定しても `/mcp` に出てこない。設定ファイルを何度も見直し、再起動を繰り返し……それでも繋がらない。

原因は **「編集していた設定ファイルが、実際にアプリが読んでいるものと違った」** という、初歩的かつ気づきにくいものでした。

Windows版のClaude Code Desktopアプリ（Microsoft Store版）は **サンドボックス化されたインストール（MSIX）** のため、実際に読み込まれる設定ファイルは次の場所にあります:

```
C:\Users\<user>\AppData\Local\Packages\<Claudeのパッケージフォルダ>\LocalCache\Roaming\Claude\claude_desktop_config.json
```

候補は他に2つありました（`~/.claude/settings.json` と通常の `AppData\Roaming\Claude\...`）が、どちらも**実際には使われていない**コピーでした。3箇所とも似たような内容が書けてしまうので、どれが「本物」か見分けがつきにくいのです。

**見分け方**: すでに繋がっている他のMCPサーバーのエントリと、UI上の接続ログ（`/mcp` → サーバー詳細）に表示される実際の起動コマンドを照合する。一致するファイルが本物です。

正しいファイルを編集したところ、一発で接続に成功し、実際に動画生成のテストも完走しました。

## まとめ

- Desktop版とCLI版では、同じ「GLM」「MiniMax」という単語が指している役割がまったく違う
- CLI版: GLMが「本体そのもの」、MCPとして意味があるのはMiniMaxのみ
- Desktop版: Sonnetが「本体」、GLM/MiniMaxは「委譲先のツール」としてMCP経由で活用
- Windows Desktop版（特にMicrosoft Store版）でMCPが繋がらない時は、サンドボックス化パッケージキャッシュ内の設定ファイルを疑う

「節約のためにMCPでGLM/MiniMaxを呼んでいる」という一言だけだと、CLI版とDesktop版の構成の違いが伝わりません。同じツールでも環境によって役割が変わる——という視点を持っておくと、設定で迷子になりにくくなると思います。
