# Zenn 半自動パブリッッシュパイプライン設計書

> 作成日: 2026-05-22
> バージョン: v2（半自動設計）
> ステータス: ドラフト（レビュー待ち）

---

## 1. 目的

自分のGitHubプロジェクト（NexusCore, Atelier, ReserveOptimizer, Orchestrix, ContextForge 等）とSSOTを定期巡回し、記事ネタを自動抽出→ドラフト生成まで自動化する。**公開は人間の承認後**に自動で行う。

## 2. パイプライン全体像

```
┌─────────────────────────────────────────────────────────┐
│  Workflow A: DISCOVER（毎日 06:00 JST）                   │
│                                                           │
│  ① スキャン: GitHub API で全リポジトリの最近の活動を取得   │
│  ② ネタ抽出: LLMが活動ログから記事ネタを抽出               │
│  ③ ドラフト生成: LLMがZenn記事ドラフトを生成               │
│  ④ プッシュ: published: false でzennリポにpush            │
│  ⑤ 通知: Discord Webhook で「ドラフト出来ました」と通知    │
│  ⑥ Issue作成: GitHub Issue にドラフト内容を貼付           │
└─────────────────────────────────────────────────────────┘
          ↓ ↓ ↓  人間が確認  ↓ ↓ ↓
┌─────────────────────────────────────────────────────────┐
│  人間の判断                                               │
│                                                           │
│  - GitHub Issue またはZennプレビューで内容確認             │
│  - 問題なければ Issue に `/approve` とコメント             │
│  - 却下なら Issue を Close                                │
└─────────────────────────────────────────────────────────┘
          ↓ /approve コメントで自動トリガー
┌─────────────────────────────────────────────────────────┐
│  Workflow B: PUBLISH（Issue コメントでトリガー）           │
│                                                           │
│  ① 記事を published: true に変更                          │
│  ② git push → Zennが自動公開を検知                        │
│  ③ 2分待機（Zenn処理待ち）                                 │
│  ④ BulkPublish API でSNS告知（X, LinkedIn, Threads等）    │
│  ⑤ Issue を Close + Discord通知「公開完了」                │
└─────────────────────────────────────────────────────────┘
```

## 3. ファイル構成

```
zenn/                                    # 既存リポジトリ
├── .github/
│   └── workflows/
│       ├── discover.yml                 # Workflow A: ネタ発見+ドラフト生成
│       └── publish.yml                  # Workflow B: 承認後の公開+SNS投稿
├── scripts/
│   ├── scanner.py                       # リポジトリスキャン
│   ├── generator.py                     # LLM記事生成
│   ├── notifier.py                      # Discord通知
│   ├── publisher.py                     # 承認→公開処理
│   ├── sns_poster.py                    # SNS告知投稿
│   ├── requirements.txt                 # Python依存関係
│   └── topic_history.json               # 過去のネタ履歴（重複防止）
└── articles/                            # 記事ディレクトリ
```

## 4. Workflow A: DISCOVER（ネタ発見+ドラフト生成）

### トリガー
```yaml
on:
  schedule:
    - cron: '21 0 * * *'   # 毎日 06:00 JST
  workflow_dispatch:        # 手動実行
```

### 処理フロー

#### Step 1: scanner.py — リポジトリスキャン

```
対象リポジトリ（fukukei23/）:
  - NexusCore
  - atelier-kyo-manager
  - reserve-optimizer
  - orchestrix
  - contextforge
  - obsidian-ssot（01_DECISIONS/ 配下）

取得する情報:
  - 過去7日間のコミット（メッセージ + 変更ファイル）
  - 過去7日間のPR（タイトル + 本文）
  - README.md の内容
```

GitHub APIを使い、各リポジトリの最近の活動をJSONで収集します。

```python
# scanner.py のイメージ
REPOS = [
    "NexusCore", "atelier-kyo-manager", "reserve-optimizer",
    "orchestrix", "contextforge",
]

def scan_repo(owner, repo, since_date):
    """過去7日間のコミットとPRを取得"""
    commits = gh_api.list_commits(owner, repo, since=since_date)
    prs = gh_api.list_pull_requests(owner, repo, state="closed", since=since_date)
    return {"repo": repo, "commits": commits, "prs": prs}
```

#### Step 2: generator.py — ネタ抽出+ドラフト生成

**2段階のLLM呼び出し:**

**呼び出し1: ネタ抽出（軽量）**
- 入力: スキャン結果のJSON + 過去のtopic_history.json（重複防止）
- 出力: 記事候補のリスト（タイトル + 概要 + 対象リポジトリ）
- モデル: GLM-5.1（コスト優先）

**呼び出し2: 記事生成（品質重視）**
- 入力: 選択されたネタ + 関連ソースコード + 関連ドキュメント
- 出力: Zenn記事Markdown（frontmatter付き、published: false）
- モデル: Claude Sonnet（品質優先）※费用は1記事あたり約$0.05〜0.10

```
ネタ抽出プロンプトのイメージ:
  「以下のGitHub活動ログから、Zenn技術記事のネタを3つ提案してください。
    過去に書いたトピック: {topic_history}
    条件: 実務経験に基づく具体的な内容、初心者にもわかる説明」
```

#### Step 3: notifier.py — Discord通知

```
Discord Webhook に送信:

📋 新しい記事ドラフトが出来ました

タイトル: {title}
リポジトリ: {repo}
プレビュー: https://github.com/fukukei23/zenn/blob/main/articles/{slug}.md

✅ 公開OK → Issueに /approve とコメント
❌ 却下 → IssueをClose
✏️ 修正 → 記事ファイルを直接編集後に /approve
```

#### Step 4: GitHub Issue作成

generator.pyが生成したドラフトの内容をIssue本文に貼り付けます。ラベル `draft-review` を付与。

---

## 5. Workflow B: PUBLISH（承認後の公開+SNS投稿）

### トリガー
```yaml
on:
  issues:
    types: [labeled]           # ラベル付与でトリガー
  issue_comment:
    types: [created]           # コメントでトリガー
```

**承認判定:** Issueに `approved` ラベルが付いた時、または `/approve` コメントが付いた時に発火。

### 処理フロー

#### Step 1: publisher.py — 公開処理

```
1. Issue本文から記事slugを特定
2. articles/<slug>.md の published: false → true に変更
3. git commit & push
4. Zennが自動検知して公開
```

#### Step 2: sns_poster.py — SNS告知

```
1. 2分待機（Zenn処理待ち）
2. BulkPublish API でチャンネル一覧を取得
3. 全チャンネルに告知投稿:
   「📝 新着記事: {title}
     https://zenn.dev/fukukei23/articles/{slug}
     #AI #LLM #Claude #エンジニア転職」
```

#### Step 3: 通知+クローズ

- Issue に「公開完了」コメントを追加してClose
- Discord に「記事公開+SNS投稿完了」通知

---

## 6. topic_history.json（重複防止）

```json
{
  "topics": [
    {
      "date": "2026-05-21",
      "title": "マルチエージェントアーキテクチャの設計",
      "slug": "multi-agent-orchestration-design",
      "source_repo": "NexusCore"
    },
    {
      "date": "2026-05-21",
      "title": "自己修復ループ設計",
      "slug": "ai-agent-self-healing-loop",
      "source_repo": "NexusCore"
    }
  ]
}
```

過去に生成したトピックを記録し、同じネタを重複して生成しないようにします。

---

## 7. GitHub Secrets

| Secret名 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 記事生成用LLM（Claude） |
| `BULK_PUBLISH_API_KEY` | SNS告知投稿 |
| `DISCORD_WEBHOOK_URL` | Discord通知 |
| `PERSONAL_ACCESS_TOKEN` | リポジトリスキャン用（GITHUB_TOKENは同一リポジトリのみアクセス可能なため） |

**4つのSecret。** channel ID等は動的取得なのでハードコード不要。

---

## 8. requirements.txt

```
anthropic>=0.30.0
PyYAML>=6.0
bulkpublish>=1.0.0
requests>=2.31.0
```

---

## 9. 人間の判断ポイント

```
Workflow A の成果物:
  ┌──────────────────────────────────────┐
  │  GitHub Issue（ラベル: draft-review）  │
  │  + Discord通知                        │
  │  + Zennリポにドラフトpush済み          │
  └──────────────────────────────────────┘
                ↓
  人間がやること（3パターンのいずれか）:

  パターン1: そのままOK
    → Issueに /approve コメント

  パターン2: 内容を修正したい
    → GitHub上で記事ファイルを直接編集
    → 編集後に /approve コメント

  パターン3: 却下
    → IssueをClose
    → ドラフトは published: false のまま残る（無害）
```

---

## 10. LLMコスト見積もり

| 処理 | モデル | 入力/出力 | 1回あたり |
|---|---|---|---|
| ネタ抽出 | GLM-5.1 | ~2k in / ~500 out | ~$0.002 |
| 記事生成 | Claude Sonnet | ~5k in / ~3k out | ~$0.05 |
| **1日あたり合計** | | | **~$0.05** |
| **月間（30日）** | | | **~$1.50** |

※LLMコストは月$1.50程度。GitHub Actions（パブリックリポ）+ BulkPublish（無料枠）は$0。

---

## 11. 既存ドラフト7本の扱い

現在 `published: false` の7本は、このパイプラインの対象外とします。

**公開方法（手動承認版）:**
1. `publish_queue.json`（旧設計）は廃止
2. 既存7本は手動で `published: true` に変更→push
3. pushを検知してWorkflow Bが発火→SNS告知

または、Workflow Bに `workflow_dispatch` でslugを渡す手動実行モードも用意:

```yaml
on:
  workflow_dispatch:
    inputs:
      slug:
        description: '記事slug'
        required: true
```

---

## 12. 設計上のトレードオフ

| 項目 | 選択 | 理由 |
|---|---|---|
| 承認方法 | GitHub Issue `/approve` | Zennリポと同一場所、Git履歴残る |
| 通知方法 | Discord Webhook | 即時性が高い、スマホで確認可能 |
| 記事生成LLM | Claude Sonnet | 日本語品質が高い |
| ネタ抽出LLM | GLM-5.1 | コスト優先、分類タスクなら十分 |
| スキャン範囲 | 過去7日間 | 1日だとネタ少ない、30日だと情報多すぎ |
| 承認後のSNS | 自動 | 人間が already checked、SNS投稿は機械的作業 |

---

## 13. 制限事項

- 記事生成の品質はLLM依存（ソースコードの文脈を取りきれない場合あり）
- 1日1ネタ抽出（複数ネタが必要な場合は手動でworkflow_dispatch連続実行）
- SNS投稿はテキストのみ（OGP画像はZennが自動生成）
- BulkPublish無料枠: 100リクエスト/日
- GitHub Actions: パブリックリポは無制限

---

## 14. 将来拡張（今はやらない）

- SSOT（obsidian-ssot）の01_DECISIONS/配下もスキャン対象に追加
- ZennスクレイピングでPV数を取得→人気記事の傾向分析
- 複数ネタ候補から人間が選択できるUI
- 記事のA/Bテスト（タイトル・構成のバリエーション）
- English翻訳版の自動生成（DEV.to等の英語圏投稿用）
