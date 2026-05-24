---
title: "OpenClaw Heartbeat設計：AIに定期的にお仕事をさせる仕組み"
emoji: "💓"
type: "tech"
topics: ["openclaw", "automation", "cron", "ai"]
published: false
---

## はじめに

OpenClaw（オープンクロー）の真価は「24時間動き続ける」ことにあります。その鍵となるのが**Heartbeat（ハートビート）**です。

Heartbeatとは、AIに定期的にタスクを実行させる仕組みです。LinuxのCron（クロン：定時タスク実行ツール）のようなものと考えると分かりやすいでしょう。

3ヶ月間の運用を通じて分かった、HeartbeatとCronの使い分けと、3層（さんそう）の設計思想を解説します。

## Heartbeat vs Cron: 2つの定期実行

OpenClawには定期実行の仕組みが2つあります:

| 項目 | Heartbeat | Cron |
|---|---|---|
| 実行間隔 | 設定ファイルに記述（柔軟） | JSONで正確な時刻指定 |
| コンテキスト | メインセッション内で実行 | 別セッションで実行 |
| タイミング精度 | ~30秒の誤差あり | 正確な時刻で発火 |
| 会話履歴 | メインセッションに残る | 独立した履歴 |
| モデル指定 | デフォルトモデル使用 | 個別にモデル指定可能 |
| チャンネル | メインチャンネル | 任意のチャンネルに配信 |

> **コンテキスト**とは、AIが「これまでの会話」を覚えている状態のことです。Heartbeatはメインの会話の中で動くため、前回の結果を参照できます。

### Heartbeatを使う場面

- 複数チェックをまとめて実行（inbox + calendar + notifications）
- 会話コンテキストが必要（前回の結果を参照する等）
- タイミングの厳密さが不要（~30分の誤差OK）

### Cronを使う場面

- 正確な時刻が必要（「毎日20:00ぴったりにYouTube要約」）
- タスクを分離したい（メインセッションを汚さない）
- 別モデルで実行したい（軽量タスクはNinjaに流す等）
- 特定チャンネルに直接配信したい

## Heartbeat 3層設計

### なぜ3層なのか

すべてを1つの間隔で回すとコストが高すぎます。重要度に応じて間隔を変えることで、コストと網羅性のバランスを取ります。

### 第1層: 30分スキャン（discord_context_scan_30m）

**目的**: Discordの会話からTODO・マネタイズのヒントを抽出

**手順**:

1. 静穏時間（22:00-06:00 JST）はスキップ → `HEARTBEAT_OK` を返す
2. 通常時間: `python3 scripts/discord_context_scan.py` を実行
3. JSON形式で「会話量」「未対応TODO候補」「リマインド候補」「マネタイズのヒント」を出力
4. 重要な提案があれば `memory/SHARED.md` に追記
5. 要約をDiscordに送信

**メンション制御**:

- @ふくけい付き: ユーザーの指示待ち、緊急案件、大きな進捗、TODO期限切れ
- メンションなし: 日常スキャン結果、特筆事項なし

**コスト**: Ninja軽量タスク → 月額約3,600円

### 第2層: 5分ヘルスチェック（Config Health Monitor）

**目的**: 設定ファイルの変更を検知して報告

**手順**:

1. `memory/config-snapshot.json` を読み込む
2. 現在の設定（timeoutSeconds, primaryModel, fallbackModels, hooks状態）を取得
3. 前回と比較して変更があればDiscordに通知
4. 新しいスナップショットを保存

**監視項目**:

- `agents.defaults.timeoutSeconds`
- `agents.defaults.model.primary` / `fallbacks`
- `hooks.internal.enabled`
- `channels.discord.enabled`

**通知先**: #openclawヘルスチェック（技術アラート用チャンネル）

**コスト**: 超軽量（比較処理のみ）→ 月額約2,000円

### 第3層: 1分ファイル監視（watch_alert_tick）

**目的**: 緊急ファイルの変更を即座に検知

**手順**:

1. `scripts/check_file_changes.sh` を実行
2. `memory/watch_alerts/` にアラートファイルがあれば通知
3. 処理済みのアラートファイルを削除
4. アラートがなければ `HEARTBEAT_OK`（ユーザーには何も表示されない）

**通知ポリシー**:

- アラートなし → HEARTBEAT_OK（サイレント）
- アラートあり → #記憶と記録に通知
- 技術的エラー → #openclawヘルスチェックに通知

**コスト**: 極軽量（ファイル存在チェックのみ）→ 月額約1,000円

## Cronジョブ一覧

Heartbeatに加えて、個別のCronジョブも運用しています。

### 監視系

| ジョブ名 | 頻度 | 内容 |
|---|---|---|
| Long Task Watcher | 5分 | サブエージェントの長時間実行タスクを監視 |
| openclaw_health_check_q6h | 6時間 | Gatewayのヘルスチェック |
| browser-relay-check | 1日2回 | Chrome Browser Relay接続状態確認 |
| LLMモデル監視 | 6時間 | openaiプロバイダー使用を検知して警告 |

### コンテンツ収集系

| ジョブ名 | 頻度 | 内容 |
|---|---|---|
| ai_news_digest_v2_brave | 1日2回 | AIニュース収集・要約 |
| AI YouTube Digest | 毎日20:00 | AI関連YouTube動画要約 |
| Weekly Ideas Collector | 火/木/土 | OpenClaw活用アイデア収集 |

### メンテナンス系

| ジョブ名 | 頻度 | 内容 |
|---|---|---|
| daily-workspace-backup | 毎日04:00 | ワークスペースバックアップ |
| daily_obsidian_note | 毎日08:00 | Obsidian日次ノート更新 |
| weekly_agent_self_diagnosis | 日曜21:00 | エージェント自己診断 |
| weekly_prompt_review_reminder | 月曜09:15 | プロンプト再学習リマインダ |
| daily_model_update_monitor | 毎日09:30 | モデルアップデート監視 |

## コスト管理ルール

新規Cron作成時は**必ずコスト計算**を記載します:

```
月額実行回数 = 頻度(回/時) × 24時間 × 30日
月額コスト(円) = 月額実行回数 × 1回平均コスト × 160円/$
```

閾値:

| 月額コスト | 判定 |
|---|---|
| ~3,000円 | OK |
| 3,000〜10,000円 | 要確認 |
| 10,000円以上 | 承認必須 |

## 静穏時間の設計

- **時間帯**: 22:00-06:00 JST（8時間）はスキャンをスキップ
- **理由**: 深夜に通知が来ても対応できない
- **効果**: 実行時間を24時間→16時間に圧縮 → コスト33%削減
- 朝起きた時に夜間分をまとめて確認できる設計

## まとめ — Heartbeat設計の5つのコツ

1. **重要度で間隔を変える** — 緊急は1分、日常は30分
2. **HeartbeatとCronを使い分ける** — コンテキストが必要ならHeartbeat、正確な時刻ならCron
3. **静穏時間を設定する** — コスト33%削減 + 通知疲れ防止
4. **コスト計算をルール化する** — 新規作成時に必ず計算
5. **サイレントOKを活用する** — アラートがない時は何も通知しない

Heartbeatは「AIにシゴトを与える」仕組みです。設計次第で24時間の監視体制を月額数千円で実現できます。

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
