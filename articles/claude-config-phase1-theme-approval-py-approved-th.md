---
title: "【claude-config Phase1】theme_approval.pyで学ぶ承認ワークフロー設計：approved_themes管理＋diffログの具体実装"
emoji: "✅"
type: "tech"
topics: ["Python", "CLI", "ワークフロー設計", "NexusCore"]
published: false
---

## はじめに

AIエージェントや自動化スクリプトを用いてコンテンツを生成・管理する際、常に悩ましいのが「人間の承認（レビュー）をどのようにシステムに組み込むか」という問題です。

完全自動化してしまうと誤った情報や不適切なコンテンツが本番環境に反映されてしまうリスクがありますが、かといって手動でのチェックを挟むとワークフローが分断され、運用コストが跳ね上がってしまいます。

この記事では、私が自身のリポジトリで進めている「claude-config Phase1」の取り組みの中で実装した `theme_approval.py` と `approve-themes` CLI について解説します。具体的には、Markdownファイルのフロントマターを用いた `approved_themes`（承認済みテーマ）の管理と、変更差分（diff）をログに記録する承認ワークフローの具体的な設計パターンを紹介します。

## 承認ワークフローの設計方針

自動生成されたテーマ（コンテンツの題目など）を承認するワークフローを設計する上で、今回以下の3つの要件を定めました。

1. **状態の永続化**: どのテーマが承認されたかを明確にし、再起動や再実行時にも状態を保持すること。
2. **差分（diff）の可視化**: 今回の実行で「どのテーマが新たに承認されたか」を明確にし、後からトレースできるようにすること。
3. **冪等性（べきとうせい）の確保**: 既に承認されたテーマを再度承認しようとしても、エラーや重複登録が起きないこと。

これらを実現するために、Markdownファイルのフロントマター（YAML形式のメタデータ）に `approved_themes` というリストを持たせるアプローチを採用しました。

## approved_themesの管理とフロントマターの保持

承認ワークフローの中核となるのが、Markdownのフロントマターを安全に更新する処理です。

Pythonでフロントマターを扱う際、単純にYAMLとしてパースして書き戻すと、開発者が手動で書いたコメントや、スクリプトが想定していない未知のキー（`custom_tags`など）が消去されてしまう問題が発生しがちです。

そこで、既存のフロントマターの構造を極力破壊しないように再構築する `_rebuild_frontmatter_preserving` というヘルパー関数を設け、未知のキーを保持したまま `approved_themes` のみを追加・更新するようにしました。

以下に、テーマを承認し、diff（差分）を算出してログに記録する具体的なコード例を示します。

```python
import yaml
from datetime import datetime
from pathlib import Path

def approve_themes_and_log(manifest_path: Path, target_themes: list[str]) -> dict:
    """
    対象のmanifestファイルのフロントマターを更新し、承認済みテーマを管理する。
    ※実装を簡略化した概念的なコードです。
    """
    # 1. ファイルの読み込みとフロントマターのパース
    content = manifest_path.read_text(encoding="utf-8")
    
    # frontmatterと本文を分割（実際にはより堅牢なパーサーを使用）
    parts = content.split('---', 2)
    if len(parts) < 3:
        raise ValueError("無効なフロントマター形式です")
    
    metadata = yaml.safe_load(parts[1]) or {}
    
    # 2. 既存の承認済みリストと差分の算出
    current_approved = set(metadata.get("approved_themes", []))
    target_set = set(target_themes)
    
    # 今回新たに承認されたテーマ（差分）
    new_additions = list(target_set - current_approved)
    
    if not new_additions:
        return {"status": "no_change", "message": "すべてのテーマは既に承認されています。"}

    # 3. ステータスの更新（冪等性の確保）
    # set を使っているため、重複を気にせず add できる
    current_approved.update(new_additions)
    metadata["approved_themes"] = sorted(list(current_approved))
    metadata["last_approved_at"] = datetime.now().isoformat()
    
    # 4. 未知のキーを保持したままフロントマターを再構築して保存
    # ※実際には _rebuild_frontmatter_preserving のような専用関数で再構築します
    updated_frontmatter = yaml.dump(metadata, allow_unicode=True, sort_keys=False)
    updated_content = f"---\n{updated_frontmatter}---\n{parts[2]}"
    manifest_path.write_text(updated_content, encoding="utf-8")

    # 5. diffログの記録
    log_message = f"[{datetime.now()}] Approved additions: {', '.join(new_additions)}"
    # ログファイルへの追記処理（省略）
    print(log_message)

    return {
        "status": "updated",
        "newly_approved": new_additions,
        "total_approved": len(current_approved)
    }
```

この実装のポイントは、**「既存のリストと今回対象のリストの差分」を算出している点**です。これにより、何度同じテーマに対して承認コマンドを実行しても（冪等性）、ファイルの更新タイミングやログの記録タイミングが「本当に新しいテーマが追加された時」に限定されます。

## CLIからの呼び出しとValueError防御

この `theme_approval.py` の関数を、実際にコマンドライン（CLI）から叩けるようにしたのが `approve-themes` コマンドです。

CLI化する際には、ユーザー（あるいは他の自動化スクリプト）からの入力値に対する**防御的プログラミング**が不可欠です。

具体的には以下の対策を組み込みました。

- **ValueErrorによる防御**: ファイルパスが存在しない場合や、Markdownの構造が壊れていてパースできない場合には、明確に `ValueError` を発生させ、CLIの終了コードを非ゼロにして呼び出し元に異常を伝えます。
- **制約の明文化**: 関数にDocstringを記述し、引数として受け取れるテーマの形式や、エラー発生時の挙動を開発ドキュメントとして明確にしました。

```python
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Markdownのテーマを承認します")
    parser.add_argument("file", help="対象のMarkdownファイルパス")
    parser.add_argument("themes", nargs="+", help="承認するテーマ名（スペース区切り）")
    
    args = parser.parse_args()
    target_file = Path(args.file)
    
    if not target_file.exists():
        print(f"エラー: ファイルが見つかりません - {target_file}", file=sys.stderr)
        sys.exit(1)
        
    try:
        result = approve_themes_and_log(target_file, args.themes)
        if result["status"] == "updated":
            print(f"承認が完了しました。追加: {result['newly_approved']}")
        else:
            print("変更はありませんでした。")
    except ValueError as e:
        # フロントマターのパース失敗などの防御
        print(f"検証エラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

CLIを経由することで、CI/CDパイプラインやAIエージェントのタスク実行エンジンから、簡単に「承認作業」を呼び出せるようになります。

## おわりに

今回は、AI等を用いたコンテンツ生成ワークフローにおいて、安全な承認プロセスを構築するための `theme_approval.py` の実装例を紹介しました。

「状態の管理」「diffの算出」「冪等性の確保」というワークフロー設計の基本要件を満たすことで、手動作業の介入を安全かつシームレスに行うことができるようになります。

自動化を進める際は、つまり「すべてを自動で行う」ことを考えがちですが、実務においては「人間が介入できる余地（承認ワークフロー）」をいかにスマートに設計するかが、システム全体の信頼性を左右します。

この記事が、皆さんのワークフロー設計の参考になれば幸いです。