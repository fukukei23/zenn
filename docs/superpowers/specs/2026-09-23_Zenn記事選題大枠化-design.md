# Zenn記事選題の大枠・体験談型化 設計spec v1.0

> date: 2026-09-23 / status: 承認済（ふくけい A選択）
> 正典: 本spec / 元データ: 01_DECISIONSは別途ssot-recordで記録
> 背景: 自動パイプライン生成記事が単発実装型に偏り、公開実績（いいね上位=体験談型）と逆行

## 1. 目的

Zenn自動生成パイプラインの選題を「大きな議題・体験談型」中心に改訂し、
公開実績で検証済みの型（♥上位6本すべて物語・体験談型・2026-09-23 API実測）に沿うようにする。
ニッチ実装記事は廃止せず「まとめ記事への群化」で再利用する（W1=就活実績の深さ証明を保持）。

## 2. 根拠データ（2026-09-23実測）

- Zenn公開API 30本のいいね数: ♥3=「OpenClaw 3ヶ月記録」「playwright-stealth自作の話」等の**物語型のみ**
- ♥0に「月間27億トークンLLMルーティング実運用レポート」等の中身が濃い技術レポート型
- 公開中約20本のうち反応あり=幅広ガイド・体験談型に集中 / 下書き約70本=単発実装型
- X自動投稿（metrics_log 16件）: 上位=大きな議題型（10-12imp）・下位=術語型（0-2imp）
- **限界**: view数は未取得（ログイン必須・PlaywrightはWindows側セッション占有中）。配合比7:3はいいねデータのみに基づく初期値

## 3. 設計判断（選択肢比較）

| 案 | 内容 | 判定 |
|---|---|---|
| A-1: generatorのプロンプトに配合指示を書くだけ | LLMの従属性のみ・機械強制なし | 却下（配合が揺らぐ・検証不能） |
| A-2: **コードで配合強制（theme_policy.py新設）+プロンプト併用** | 機械的検証可能・LLM揺らぎに耐性 | **採用** |
| A-3: 生成後に全部捨てて再生成 | トークン浪費 | 却下 |

- **採用=A-2**: 純関数で配合強制しテストで検証する（LLMの確率的揺らぎをコードで吸収するのが本パイプラインの既存設計思想・extract_topicsの3リトライと同型）

## 4. 実装内容（4点）

### 4-1. theme_policy.py 新設（純関数・TDD対象）
- `classify_topic_type(title, summary) -> "cross" | "single"`: 題名・概要のヒューリスティック分類（「〜した話」「入門」「ガイド」「まとめ」「一年/記録」「比較」「設計」→cross寄り・特定バグ名/単一関数名/エラー名→single寄り）
- `enforce_theme_ratio(topics, cross_ratio=0.7) -> list`: MiniMax提案3件を型分類し、cross不足ならLLM再提案を促すフラグを返す（リトライはgenerator側・既存3リトライ構造に乗る）
- 戻り値は `(filtered_topics, needs_regenerate)` のタプル

### 4-2. generator.py 改修（既存構造に接続・Surgical Changes）
- `extract_topics` のプロンプトに配合指示を追記（「3件中2件以上は複数活動を横断する大きな議題・体験談型にすること」）
- 提案受領後に `enforce_theme_ratio` を適用 → 不足時は既存リトライ内で再生成

### 4-3. ranker.py 改修（4軸目「入口の広さ」追加・合計は変更しない）
- 採点プロンプトに `reach`（1-10・初心者に読める入口か/固有名詞依存度）を追加
- **既存の合計（バズ+技術+重要・最大30）は維持**（既存行との冪等性・ソート互換保持）— reachは新列表示+grade補助にのみ使用
- grade判定追加: `reach <= 3` かつ単発型 → 「群化候補」マーク（C級説明文を更新）

### 4-4. bundler.py 新設（群化ジェネレータ・TDD対象）
- `group_by_theme(articles) -> dict[theme, list[article]]`: C級・単発型記事をテーマ語（pytest/CLI/セキュリティ/Claude Code hook等・タグと題名から決定的に抽出）で束ねる
- `bundle_proposals(groups, min_size=3) -> list[提案]`: 3本以上の群からまとめ記事の目次案（タイトル+章リスト）を生成
- LLM呼出なし（決定的・テスト可能）・目次案の本文化は人間or手動実行

### 4-5. 体験談テンプレ
- `docs/テンプレ_体験談.md` 新設（articles/配下でない=publisher対象外）
- 公開済み♥上位6本（OpenClaw記録/playwright-stealth自作/14エージェント/20プロジェクト/SSOT知見/武器庫）の共通構造を抽出: 経緯→壁→試行→数字→学び

## 5. テスト計画

- `scripts/test_theme_policy.py`: 分類ヒューリスティックの正常系/境界（体験談タイトル→cross・エラー名タイトル→single・空文字）/配合強制（cross0件でneeds_regenerate=True・3件全crossでFalse）
- `scripts/test_bundler.py`: グルーピング（同テーマ束ね・min_size未満除外・テーマ語抽出）
- `scripts/test_generator.py`: 既存テストが壊れないこと（回帰）
- ruff 全パス

## 6. fail条件・限界

- fail条件: 生成3回リトライでもcross不足が解消されない場合、当日は単発型のみで生成される（現行より劣化しない・needs_regenerate記録をgenerator_error.jsonに残す）
- 配合比7:3は初期値・view数取得後に再校正する（view数=ログイン必須・PlaywrightがWindows側と競合中）
- reach採点はLLM判断なので、単発型でも高reachになり得る（その場合群化候補にならず公開候補のまま=誤殺防止）

## 7. スコープ外

- 既存下書き70本の一括群化実行（bundlerの初回実行は別タスク・ふくけい承認制）
- X自動投稿（sns_poster）のテーマ改訂（本specはZenn生成のみ）
