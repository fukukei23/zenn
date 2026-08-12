---
title: "【claude-config】aiwatch日本語翻訳パイプラインの実装：3フィールドで運用負荷軽減"
emoji: "📝"
type: "tech"
topics: ["Python", "ClaudeCode", "LLM"]
published: false
---

title: "【claude-config】aiwatch日本語翻訳パイプラインの実装：3フィールドで運用負荷軽減"
emoji: "🤖"
type: "tech"
topics: ["Python", "ClaudeCode", "LLM"]
published: false
---

## はじめに

LLM（大規模言語モデル）を用いたタスク自動化は、開発の生産性を劇的に向上させます。しかし、LLMの出力をシステムやデータベースにそのまま取り込んでしまうと、フォーマットの揺れや予期せぬエラーが発生し、かえって運用負荷が増大してしまうことがあります。

今回は、私がGitHub上で管理しているプロジェクトにおいて、AIによる監視データ（description）の日本語翻訳パイプラインを構築した経験をもとに、「LLM出力の安全管理」と「運用負荷の軽減」を実現するための実践的なアプローチを解説します。

## LLM出力をそのまま使ってはいけない理由

LLMにテキストの翻訳や要約を任せる際、陥りがちなのが「LLMの返り値をそのまま1つのテキストフィールドに保存してしまう」という設計です。

この場合、以下のような問題が発生しがちです。

1. **UIでの表示崩れ**: 詳細な文脈が必要な長文テキストが、リスト一覧の短い概要欄に表示されてしまう。
2. **検索ノイズの発生**: Markdownの装飾記号（`**` や `#` など）がDBに混ざり、全文検索時にノイズになる。
3. **LLM特有のバイアス**: プロンプトの指示通りにいかず、LLMが勝手に情報を省略（サボり）してしまうことがある。

これらを防ぐためには、LLMの出力をそのままシステムに投入するのではなく、用途に合わせて適切に処理する「パイプライン」を挟む必要があります。

## 3フィールド構造による安全なデータ管理

今回の実装では、LLMが翻訳・生成したテキストを受け取った後、システム側で以下の3つのフィールド構造に分割して管理する設計を採用しました。

- `summary`: UIのリスト表示等で使う短縮版テキスト（数十文字程度）
- `detail`: 詳細画面等で表示する完全版テキスト（Markdown等のフォーマットを許容）
- `plain`: インデックス作成や検索エンジン用のプレーンテキスト（記号類をすべて除去）

このようにデータを振り分けておくことで、フロントエンド側の要件変更が発生しても、バックエンドやLLMのプロンプトを修正することなく柔軟に対応できるようになります。

以下に、PythonでLLMの生テキストを3フィールドに変換・保存する実装例を示します。

```python
import json
from pathlib import Path

def process_llm_translation(raw_text: str) -> dict:
    """
    LLMから受け取った生のテキストを、3フィールド構造に変換する
    """
    # summary: 最初の50文字を取得し、超過場合は省略記号をつける
    summary_text = raw_text[:50].rstrip() + ("..." if len(raw_text) > 50 else "")
    
    # plain: Markdownなどの記号をシンプルに除去する（実務では正規表現等で厳密に処理）
    plain_text = raw_text.replace("**", "").replace("#", "").replace("`", "")
    
    return {
        "summary": summary_text,
        "detail": raw_text,
        "plain": plain_text
    }

def save_translation(data: dict, filename: str):
    # パスはハードコードを避け、環境変数等を汎用的に解決する
    output_dir_str = "/path/to/translations"
    output_dir = Path(output_dir_str)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / f"{filename}.json"
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), 
        encoding="utf-8"
    )

# 実行例
if __name__ == "__main__":
    llm_response = "## 概要\nこれは**AIによる翻訳パイプライン**のテストです。"
    processed_data = process_llm_translation(llm_response)
    save_translation(processed_data, "aiwatch_desc_001")
```

このような仕組みを用意しておくことで、LLMが多少予期せぬフォーマットで出力しても、システム側で安全に吸収することができます。

## 安定稼働のためのタイムアウト延長と環境依存の排除

LLMを利用したパイプラインでは、APIの応答遅延による「タイムアウトエラー」が頻発します。特に、複雑なプロンプトを与えたり、長文の翻訳を処理させたりする場合、デフォルトのタイムアウト値（30秒や60秒など）では処理が完了しないことがあります。

今回の実装においても、安定稼働のためにAPI呼び出しのタイムアウトを延長する対応を行いました。バッチ処理や非同期タスクでLLMを利用する場合は、タイムアウトを長め（例: 120秒〜300秒）に設定し、適切なリトライ処理を組み合わせることが重要です。

### スクリプトの移植性向上（環境依存パスの排除）

運用負荷を下げるもう一つの重要なポイントが「スクリプトの移植性」です。
以前のスクリプト内に特定の実行環境に依存するパス（例: 特定のPCのユーザーディレクトリ）がハードコードされていると、新しいPCへの移行時やチーム開発の際にスクリプトが動かなくなってしまいます。

これを防ぐため、Pythonの `pathlib.Path` を活用し、どの環境でも動作するような書き方にリファクタリングしました。

```python
import os
from pathlib import Path

def get_log_file_path() -> Path:
    """
    環境変数をもとに、実行環境に依存しないログディレクトリを解決する
    """
    # 環境変数からログディレクトリを取得（未設定の場合はデフォルトの汎用パスを使用）
    log_dir_str = os.getenv("APP_LOG_DIR", "/path/to/default/logs")
    log_dir = Path(log_dir_str)
    
    # ディレクトリが存在しない場合は作成
    log_dir.mkdir(parents=True, exist_ok=True)
    
    return log_dir / "aiwatch_pipeline.log"

# 実行環境に依存せず安全にパスを取得できる
log_path = get_log_file_path()
```

このように、「LLM出力の加工ロジック」と「実行環境への依存を排除するインフラ部分」の両方を整備することで、メンテナンスフリーに近い堅牢なパイプラインを構築できます。

## おわりに

LLMは強力なツールですが、その出力の気まぐれ（サボりバイアスやフォーマットの揺れ）をシステム側でうまくコントロールしてあげる必要があります。

- **LLMの出力を用途別に3フィールド（summary, detail, plain）で管理**すること
- **タイムアウトを延長**し、安定したAPI通信を行うこと
- **パスの展開を工夫**し、環境に依存しない堅牢なスクリプトを書くこと

これらの実践的なアプローチを取り入れることで、長期間安定して稼働するLLM翻訳パイプラインを構築できます。AIを用いた自動化パイプラインの設計に迷った際は、ぜひ参考にしてみてください。