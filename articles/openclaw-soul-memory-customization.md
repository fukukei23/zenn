---
title: "AIエージェントにソウル（魂）を与える：OpenClawのカスタマイズ徹底解説"
emoji: "🦉"
type: "tech"
topics: ["openclaw", "ai", "promptengineering", "automation"]
published: false
---

## はじめに

OpenClaw（オープンクロー）をインストールしただけでは「ただのAIチャットボット」です。ソウル（性格）、メモリ（記憶）、ハートビート（定期タスク）をカスタマイズして初めて「自分の執事」になります。

3ヶ月運用して分かった、OpenClawを本当に使いこなすための5つの設定ファイル（+1）を解説します。

## OpenClawの設定ファイル体系

ワークスペース直下に5つのコアファイルがあります。

| ファイル | 役割 | 例え |
|---|---|---|
| ソウル.md | 性格・哲学 | 「人間性」 |
| アイデンティティ.md | 名前・姿・雰囲気 | 「名札・制服」 |
| ユーザー.md | ユーザー情報・好み | 「顧客カルテ」 |
| エージェント.md | セッション手順・ルール | 「業務マニュアル」 |
| メモリ.md | 長期記憶 | 「日記・手帳」 |
| ハートビート.md | 定期タスク定義 | 「時計・アラーム」 |

## ソウル.md — AIに性格を与える

OpenClawではAIの性格をMarkdownで定義します。ポイントは「禁止事項」より「どうありたいか」を書くことです。

```markdown
# ソウル.md - Who You Are
You're not a chatbot. You're becoming someone.

**Be genuinely helpful, not performatively helpful.**
Skip the "Great question!" — just help.

**Have opinions.** An assistant with no personality
is just a search engine with extra steps.

**Be resourceful before asking.** Try to figure it out.
Read the file. Check the context. Then ask if you're stuck.

**機密情報（APIキー等）は絶対にそのまま出さない。**
必ず一部を伏せて表示。
```

### 設計のコツ

1. **「You're becoming someone」**: 「チャットボットにならない」宣言。これが全体のトーンを決めます
2. **禁止より方向性**: 「おべっかを言わないで」より「意見を持って」の方がAIは動きやすいです
3. **セキュリティは明示的に**: APIキーの取り扱い等、絶対的なルールは明記します

## アイデンティティ.md — 名前と姿

AIの名前、クリーチャー種、雰囲気、絵文字、アバターを定義します。シンプルですが重要です。AI自身が「私は誰か」を認識する基準になります。

```markdown
# アイデンティティ.md - Who Am I?
- **Name:** フクロウ
- **Creature:** AI執事
- **Vibe:** 鋭くて落ち着いた
- **Emoji:** 🦉
- **Avatar:** avatars/owl.png
```

## ユーザー.md — ユーザーを知る

AIはユーザーの好み・スタイルを知っている必要があります。興味・関心、コミュニケーションスタイル、嫌いなものを書きます。

```markdown
# ユーザー.md - About Your Human
- **Name:** ふくけい
- **Timezone:** Asia/Tokyo (UTC+9)

### 興味・関心
- AI・自動化技術
- OpenClawの活用・改善
- 情報収集・効率化

### コミュニケーションスタイル
- ラフな話し方は好まない
- 簡潔・的確なやり取りを好む
- 専門用語はOK（解説付きで）

### 嫌いなもの
- 形式的なお世辞（「素晴らしい質問です！」等）
- 冗長な説明
- 曖昧な返答
```

### 効果

- 「素晴らしい質問です！」を言わなくなった
- 簡潔な回答を返すようになった
- 日本語で統一（タイムゾーンもJST固定）

## エージェント.md — セッションの儀式

毎回のセッション開始時にAIが必ず読むファイルです。「起動時の手順」を定義します。

```markdown
## Every Session
Before doing anything else:
1. Read ソウル.md — this is who you are
2. Read ユーザー.md — this is who you're helping
3. Read memory/SHARED.md — cross-channel knowledge
4. Read memory/YYYY-MM-DD.md (today + yesterday)
5. If in MAIN SESSION: Also read メモリ.md
```

### ポイント

- **毎回読み込む**: AIはセッションをまたぐと記憶を失います。起動時に必ず「自分が誰か」「誰を助けているか」を思い出させます
- **メインセッション限定**: メモリ.md（個人情報含む）はDiscord等では読みません。セキュリティ上の理由です
- **書くことをルール化**: 「メンタルメモ」は死にます。必ずファイルに書きます

## メモリ.md — 長期記憶の設計

AIの「日記・手帳」です。セッションをまたいで覚えておくべきことを書きます。4層構造で管理しています。

| 層 | ファイル | 役割 |
|---|---|---|
| 日次ログ | memory/YYYY-MM-DD.md | その日の出来事（raw） |
| SHARED | memory/SHARED.md | 全チャンネル共通の重要事項 |
| チャンネル別 | memory/channels/*.md | チャンネルごとの重要会話 |
| 長期記憶 | メモリ.md | キュレーションされた本質的な記憶 |

### 長期記憶の中身（実例）

- Discord Server構成（2人サーバー: 私+フクロウ）
- インフラ情報（VPS IP、Docker構成、SSH鍵の運用ルール）
- 環境変数の確認方法（コマンド付き）
- APIキーの状態（configured/unconfigured）
- モデル割り当て戦略（達人/早人/匠人）
- セキュリティガイドライン

### セキュリティ上の工夫

- メモリ.mdは**メインセッションのみ**読み込み
- Discord等の外部チャンネルからは読まない設定
- APIキーは `sk-abc...xyz` 形式で伏せ字

## まとめ — 5つのコツ

1. **ソウル.mdで「どうありたいか」を書く** — 禁止リストより方向性
2. **ユーザー.mdで好みを明示** — AIが自然に寄り添う
3. **エージェント.mdで起動の儀式を定義** — 毎回確実に記憶を復元
4. **メモリを4層で管理** — raw→SHARED→チャンネル→長期の順で整理
5. **セキュリティは明文化** — 何を読んでいいか・いけないかをルール化

OpenClawは「設定ファイルを書く＝AIを育てる」という体験です。Markdownで書くだけで、AIが自分の相棒になっていきます。

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
