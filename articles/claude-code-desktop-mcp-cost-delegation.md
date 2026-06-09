---
title: "CLI版とDesktop版でGLM/MiniMaxの役割がまるで違う話"
emoji: "🔀"
type: "tech"
topics: ["claudecode", "mcp", "llm", "glm", "claude"]
published: false
---

## はじめに

Claude CodeのCLI版でGLMを使っている、という話を以前書きました。同じ流れでDesktop版にも設定しようとしたのですが、CLIとDesktopでは**GLM/MiniMaxの立ち位置がまったく別物**でした。

同じ単語が使われているのに役割が逆転していて、それを知らずに設定すると「なぜか繋がらない」「節約できていない」という沼にハマります。この記事ではその違いを整理します。

## 環境によって役割がまるで違う

| | WSL CLI版 | Windows Desktop版 |
|---|---|---|
| **本体（ベースモデル）** | GLM-5.1（ZAI API経由） | 本物のSonnet（Anthropic OAuth） |
| **節約の仕組み** | エンドポイント自体をGLMに差し替える | MCP経由でGLM/MiniMaxに委譲 |
| **GLMの位置づけ** | Claude Codeの正体そのもの | 外部ツール（MCPサーバー） |
| **MCPとして意味があるもの** | MiniMaxのみ（GLMは二重呼び出しになる） | GLM・MiniMax両方 |

「GLMを使ってコストを下げる」という目的は同じでも、構成がまったく違います。

## CLI版: エンドポイントを丸ごと差し替える

CLI版は  を書き換えるだけで通信先をGLMに向けられます。Claude Codeという皮を被ったGLMとして動く構成です。



この構成ではGLMが「本体そのもの」なので、わざわざMCP経由でGLMを呼び出すと**GLMがGLMを呼ぶ二重構造**になり無意味です。CLI版でMCPとして実用上意味があるのはMiniMaxだけです。

## Desktop版: MCPで委譲口を作る

Desktop版（特にMicrosoft Store版）は環境変数の書き換えができず、Sonnet固定で動きます。エンドポイントを差し替えるという方法自体が使えない。

そこでMCPを使い、Sonnetの外側に安いLLMへの「出口」を作ります。



この構成ではGLMもMiniMaxも「委譲先の外部ツール」なので、両方MCPとして意味を持ちます。

## 混同するとどうなるか

- **CLI版でglm MCPを設定する** → 二重呼び出しで無意味（CLAUDE.mdにも「不要・不可」と明記するほど）
- **Desktop版でANTHROPIC_BASE_URLを書き換えようとする** → そもそも反映されない

どちらも「動かないのに設定ミスを疑って迷宮入り」というパターンにハマります。

## まとめ

- CLI版: GLMが「本体」、MCP経由で意味があるのはMiniMaxのみ
- Desktop版: Sonnetが「本体」、GLM/MiniMaxは「委譲先のツール」としてMCP経由で活用
- 同じ単語でも環境で役割が逆転する——という前提を持っておくと設定で迷子にならずに済む

---

## 関連記事

- [Desktop版でのMCPコスト削減の具体的な設定方法](./claude-code-desktop-mcp-cost-reduction) — 実際の設定手順はこちら

---

この記事はClaude Code（GLM-5.1）と一緒に書きました。
