---
date: 2026-11-26
project: zenn
status: approved
mlr: 3ラウンド（r1=55件・r2=51件・r3=64件・計170指摘・収束確認済み）
mlr_log: ~/projects/obsidian-ssot/60_MLR_LOGS/2026-11-26_zenn-discord-approval/revised_proposal.md
related:
  - docs/auto-publish-pipeline-design.md
  - 01_DECISIONS/x-automation/2026-07-12_Phase-C-Discord承認bot実装完了.md
---

# Zennドラフト Discord承認パイプライン設計（2026-11-26承認）

## 当初目的

スマホのDiscord通知→👍リアクション1タップで承認→最大約1時間以内に記事が自動公開される、人間参加型のZenn投稿パイプラインを実現する。本人の承認操作をDiscord上で完結させ・CCが承認を代行しない。

## 背景と実測事実

- 承認が6ヶ月間ゼロ（2026-05-29最終公開）: スマホからGitHubのissueページを開いて`/approve`をコメントする操作が実質不能・Discord通知には「Issueに/approveとコメント」としか書かれていない
- 発見側（discover.yml）は毎日正常稼働・ドラフトissueが100件超滞留
- 公開側（publish.yml）は本日実測成功（issue #106・全13ステップ成功・2m54s）
- **実測確定**: PAT投稿コメント=OWNER・github-actions[bot]投稿=CONTRIBUTOR（#106のコメントAPI実測）→ PAT転送ならOWNER判定を通る・GITHUB_TOKEN転送なら通らない（publish.yml:16のauthor_association条件）
- **実測確定**: publish.yml:45のif条件は`gate=='clean'`のみ → 品質ゲート修正時（gate=fixed）は公開ステップがスキップされ再承認待ちで停止
- X自動化プロジェクトの`get_approval_decision`（承認者ID照合方式）でbot初期👍は構造的に除外される（lib/discord_client.py実在・本番運用中）

## 設計: 全体フロー（8ステップ）

### 日次（既存・変更なし）

1. **discover.yml**: ドラフト生成 → GitHub issue作成
2. **notifier.py（拡張）**: Discordに「承認メッセージ」をbot送信
   - 文面: 「このメッセージの👍をタップすると公開されます（自発で👎を付けると却下です）・通常は最長約90分以内で公開処理が進みます」
   - bot自身が👍のみ初期付与（初期👎は誤タップ却下の誘発防止）
   - 通知文面に誤却下復旧手順を1行明記
   - message_id・issue番号・ドラフト本文hash（frontmatter除外・SHA-256）を `docs/discord_messages.json` に記録

### ふくけいの操作（スマホのみ）

3. 通知を見る → 👍をタップ（操作はこれだけ）

### 自動（最大約1時間〜90分）

4. **approve-check.yml（新設・毎時実行・concurrency設定付き）**
   - 判定対象: 未処理jsonエントリのみ
   - 判定方式: 承認者ID照合（fukukei23のIDが👍付けたかのみ判定・botの初期👍は構造的に除外）
   - 承認者限定: 👍/👎ともfukukei23のユーザーIDのみ有効・他人は無視
   - ドラフト内容hash照合: 通知時と現在のarticle本文hashが不一致なら転送停止→新しい承認メッセージを自動再送（1日1回上限・旧メッセージにbot⚠️注記）
   - 👍 → PAT（fine-grained・issues:write単一・当リポジトリ限定）でissueに `/approve` 投稿（本文に「via Discord reaction msg_id=<id> at <ts>」を記録=監査性）
     - 転送成功後にjsonエントリを削除（二重転送防止）
   - 👎 → issueを却下Close → jsonエントリ削除
   - checker自体の失敗時にDiscordへエラー通知
   - 403/401検知時もDiscord通知（PAT期限切れ等の滞留防止）

### 既存パイプライン（publish.yml・トリガー条件と公開ロジックは不変）

5. PAT投稿の /approve は OWNER author_association を持つため既存トリガー条件を通る → publish.yml発火 → 日本語品質ゲート → Zenn公開
6. issue自動Close（Published URL付き）

### 品質ゲートで修正が入った場合

7. publish.ymlのja_gateステップ後にgate=fixed条件で再承認メッセージ再送ステップを1つ追加（ja_quality_fix.py自体は変更不要）→ 新しい承認メッセージをbot再送（diff概要+修正理由付き・**修正後のarticle本文を再hashしてjson更新**）→ ふくけいはそのメッセージに👍 → approve-check.ymlが次回判定で再転送 → 再承認もDiscord完結
   - ループ上限: 同一issueで3回を上限（再承認要求発行時のみインクリメント）・超過時は「手動確認へ降格」のDiscord通知

8. 完了通知（webhook・変更なし）

## 設計の柱

| 項目 | 決定 | 根拠 |
|---|---|---|
| 承認方式 | 👍リアクション（bot初期付与は👍のみ） | タップ1回・X自動化と同型 |
| 判定対象 | 承認者ID照合方式（X自動化と同一・botの初期👍は構造的に除外される） | bot自身の👍誤検知を構造的に排除 |
| 再承認 | 修正後もDiscord完結・ループ上限3回 | 6機合流指摘（r1）+GLM critical（r2） |
| 転送トークン | PAT（fine-grained・issues:write単一）で/approve投稿・転送本文にDiscord由来記録 | PAT=OWNER実測・bot=CONTRIBUTOR≠OWNER実測 |
| 公開の速さ | 約1時間〜最大90分・E2E 5回実測+30日継続測定 | Actions cron遅延込みの要件正確化 |
| 状態管理 | json記録+転送成功時エントリ削除+workflow concurrency+push前git pull --rebase（衝突時GitHub API再検証） | 二重転送防止 |
| 承認バインディング | 本文（frontmatter除外）SHA-256・不一致なら1日1回上限で再通知 | 承認後の内容差替え防止 |
| 誤却下復旧 | 却下済みメッセージへの再👍で自動復旧（rejected状態をjsonに30日保持） | スマホ完結目的の穴を埋める |
| bot権限 | 最小権限（Send Messages + Add Reactions + Read Message History） | token漏洩時の影響限定 |
| チャンネル | webhook経由でchannel_id解決+Phase 0で同一チャンネル実測必須 | bot権限の実測保証 |
| publish.yml | トリガー条件・公開ロジックは不変・ja_gate後に再送ステップ1点追加 | 既存フロー流用の柱 |

## Phase 0運用ゲート（測定完了まで本番運用は試験的）

1. **E2E所要5回実測+30日継続測定**: 👍タップ時刻→公開完了時刻をjsonに記録・初期昇格は5回中90分以内4回以上+30日継続測定で90分超え2回以下+公開重複ゼロを必須gateとする・超過時はapprove-check.ymlを30分毎cronへ変更
2. **author_association実測**: PATで投稿した/approveがOWNER判定を通ることを1回の実転送で確認・PAT投稿からpublish run生成までを含めて検証（fail時はpublish.ymlトリガー条件をPAT許可へ変更）
3. **bot権限実測**: bot送信・👍初期付与・リアクション取得・404検知が同一チャンネルで成功+絵文字照合実測（bot初期👍とふくけいのスマホ👍が同一emoji・unicode codepointでAPI応答に返ること）
4. **他人のリアクション無視実測**: 承認者ID以外のダミーuser_idを使ったapprove_checker.py単体テスト+Discord実測は「ふくけいの👍のみ転送されること」を1回
5. **再承認フロー実測**: 品質ゲート修正が実際に発生した最初の1件で、再承認メッセージ→再タップ→再転送→公開が完結することを確認
6. **失敗時アラート実測**: checkerを意図的に失敗させDiscord通知が届くことを確認

## エッジケース対応

- メッセージ削除（404）: エントリ削除・再通知は新issue（翌日のdiscover）で自然に別物
- 👍と👎が両方付いた場合: 👎優先（安全側維持）・誤却下は却下済みメッセージへの再👍で自動復旧（rejected状態をjsonに30日間保持・approve_checker.pyが再👍を検知→issue再オープン+転送を自動実行・文面案内はfallback）
- 再承認ループ: 同一issueで3回を上限（超過時は「手動確認へ降格」のDiscord通知）
- 反応がない場合: 30日超過エントリはcheckerの清掃で削除（ステータス履歴はGitHub issue側に残る）
- リアクション取得: limit=100（1ページ・超過時はページネーション処理を実装）・「取得失敗≠未承認」（APIエラー時は判定保留）
- 品質ゲート修正: 再承認メッセージ再送でDiscord完結・修正後の本文を再hashしてjson更新

## ロールバック手順（問題発生時）

1. approve-check.ymlをGitHub ActionsのUIから無効化（承認判定のみ停止・即時・UI完結）
2. その後: notifier.pyを旧webhook送信にrevert（コードrevertはcommitが必要・事後ステップ）
3. jsonの手動クリーンアップ

## 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `scripts/notifier.py` | bot送信化+誘導文面+👍初期付与+json記録（message_id・issue番号・draft hash） |
| `scripts/reapprover.py`（新設またはnotifier.py内関数） | 品質ゲート修正時の再承認メッセージ再送・修正後の本文再hash |
| `.github/workflows/approve-check.yml` | 新設（毎時+concurrency・PAT転送・hash照合・エントリ削除・エラー通知） |
| `scripts/approve_checker.py` | 新設（判定ロジック・承認者ID照合・hash照合・TDD・絵文字正規化・pull --rebase+衝突時GitHub API再検証・ループ上限3回・rejected状態保持30日による再👍自動復旧・403/401検知Discord通知） |
| `publish.yml` | ja_gateステップ後にgate=fixed条件の再送ステップを1つ追加（トリガー条件・公開ロジックは不変） |
| GitHub secrets | `DISCORD_BOT_TOKEN` 追加（PATは実在済み・fine-grained化は実装時に新規発行） |

## MLR経緯

3ラウンド（r1=55件・r2=51件・r3=64件・計170指摘）。採用指摘は全て本設計に反映済み。詳細: `~/projects/obsidian-ssot/60_MLR_LOGS/2026-11-26_zenn-discord-approval/review_log.md`（全170指摘の採否記録）・`revised_proposal.md`（r3版改訂案）。r3でGLM 8件が全て対応済み（r1/r2採用済み対策の再指摘のみ）=収束確認。
