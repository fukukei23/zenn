---
title: "【初心者向け】PythonでWikilinkをMarkdownに変換：TDDで実装する1ファイルスクリプト"
emoji: "📝"
type: "tech"
topics: ["Python", "TDD", "Obsidian", "Markdown"]
published: false
---

```markdown
title: "【初心者向け】PythonでWikilinkをMarkdownに変換：TDDで実装する1ファイルスクリプト"
emoji: "🐍"
type: "tech"
topics: ["Python", "TDD", "Obsidian", "Markdown"]
published: false
```

## はじめに

Obsidianなどのメモアプリを使っていると、内部リンクである「Wikilink記法（`[[ページ名]]`）」に非常に慣れてしまいます。しかし、そのメモをZennやGitHubなどの外部プラットフォームに公開・移行しようとしたとき、Wikilinkは標準的なMarkdownリンク（`[表示名](URL)`）として認識されず、リンクが切れてしまう問題に直面します。

手動で数十、数百のリンクを修正するのは非現実的です。

この記事では、**ObsidianのWikilinkを標準Markdownリンクに変換するPythonスクリプト**を、**TDD（テスト駆動開発）**で実装する手順を初心者向けに解説します。実際の開発現場で得た知見をもとに、`base_url`設定などの実用的な拡張ポイントや、「スクリプトを使い捨てにする」という運用の Tips も紹介します。

## 対象とする変換ルールとTDDの準備

まずは、スクリプトに期待する変換ルールを整理します。

1. **基本変換**: `[[ページ名]]` → `[ページ名](ページ名)`
2. **エイリアス（表示名）付き**: `[[ページ名|表示名]]` → `[表示名](ページ名)`
3. **実用拡張（base_url）**: リンク先が同じファイル内にあるとは限りません。GitHubの特定ディレクトリなど、共通のURL（`base_url`）を前置できるようにします。

TDDでは、まず「期待される動作」を記述した**テストコードを書き、それをパスするように実装**を行います。今回はPythonの標準的なテストツールである `pytest` を使います。

以下は、上記ルールを網羅したテストコードです。

```python
# test_converter.py
import pytest
from converter import convert_wikilinks

def test_basic_wikilink():
    # 1. 基本変換のテスト
    text = "ここは[[ページ名]]です。"
    expected = "ここは[ページ名](ページ名)です。"
    assert convert_wikilinks(text) == expected

def test_alias_wikilink():
    # 2. エイリアス付きのテスト
    text = "詳細は[[ページ名|コチラ]]を参照。"
    expected = "詳細は[コチラ](ページ名)を参照。"
    assert convert_wikilinks(text) == expected

def test_base_url_prefix():
    # 3. base_url 付きのテスト
    text = "[[ページ名]]"
    expected = "[ページ名](/path/to/docs/ページ名)"
    assert convert_wikilinks(text, base_url="/path/to/docs") == expected
```

このテストを実行すると、まだ `converter.py` に実装がないためエラー（Red）になります。次に、このテストを通すため（Green）の最小限の実装に進みます。

## 正規表現によるPythonスクリプトの実装

テストをパスさせるために、Pythonの `re` モジュール（正規表現）を使った1ファイル完結のスクリプトを実装します。

Wikilinkは `[[` から始まり `]]` で終わります。その間に「ページ名」のみがあるパターンと、「ページ名|エイリアス」があるパターンの2種類があります。これを正規表現のキャプチャグループ（カッコ `()`）を使って抽出します。

```python
# converter.py
import re

def convert_wikilinks(text: str, base_url: str = "") -> str:
    """
    Wikilink ([[...]]) を標準Markdownリンクに変換する
    """
    # Wikilinkを抽出する正規表現
    # group(1): ページ名, group(2): エイリアス（存在する場合）
    pattern = r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'
    
    def replacer(match):
        page_name = match.group(1).strip()
        alias = match.group(2)
        
        # base_url が設定されている場合は、URLの前に付与
        # サブディレクトリなどを考慮してスラッシュの有無を調整
        prefix = f"{base_url}/" if base_url and not base_url.endswith('/') else base_url
        url = f"{prefix}{page_name}"
        
        # エイリアスが存在しない場合は、リンクの表示名もページ名にする
        link_text = alias.strip() if alias else page_name
        
        return f"[{link_text}]({url})"

    # 正規表現にマッチした部分を replacer 関数で置換
    return re.sub(pattern, replacer, text)

if __name__ == "__main__":
    # コマンドラインから簡単に試せるようにする例
    sample_text = "[[Python]]と[[TDD|テスト駆動開発]]のメモです。"
    print(convert_wikilinks(sample_text, base_url="/wiki"))
```

この実装により、先ほどのテストコードはすべてパスします。

このように、複数行にわたるテキストの中から特定のパターンだけを置換したい場合、`re.sub` の第二引数に「置換処理を書いた関数（コールバック関数）」を渡すのがPythonらしいスマートな書き方です。初心者の方は、この `re.sub` と無名関数（または通常の関数）の組み合わせを覚えておくと、テキスト処理の幅が一気に広がります。

## 実務での運用：スクリプトは「使い捨て」にする

さて、無事に実装とテストが完了しました。実際のプロジェクト（自分のリポジトリ）にこのスクリプトを組み込む際の運用面での Tips を紹介します。

今回の私のケースでは、Obsidianで管理していたドキュメントを、システムの都合上サブレポジトリ（別ディレクトリ）に分割して移行する必要がありました。その際、大量のWikilinkを新しいパス（`/path/to/sub-repo/...`）に合わせて標準Markdownに変換するために、このスクリプトを作成しました。

そして、**変換作業がすべて完了した直後に、このスクリプトはリポジトリから削除（Gitの履歴のみ残す）しました。**

なぜ残さないのか？それは、**「変換処理は1回限りのワンショット（one-shot）だから」**です。
変換後のドキュメントが標準Markdownで管理されるようになれば、このスクリプトは二度と実行されることがありません。にもかかわらず、スクリプトをリポジトリに残しておくと、将来的に「これは何のスクリプトだ？」「メンテナンスが必要か？」と、他の開発者（未来の自分を含む）の認知負荷を高めてしまいます。

TDDで小さなスクリプトを書く最大の利点は、**「後から見返したときに、このコードが何を意図して作られたか（どう動くべきか）がテストコードとして明確に残る」**ことです。実行用のスクリプト自体は使い捨ててしまっても、Gitのコミットメッセージ（例：`feat: wikilink変換スクリプト追加` → `chore: 変換完了後、スクリプト自削除`）とテストコードと一緒に履歴に残しておけば、十分に実用的な知見として蓄積されます。

## おわりに

この記事では、ObsidianのWikilinkを標準Markdownに変換するスクリプトを、TDDで実装する方法を解説しました。

- **正規表現と `re.sub` のコールバック関数**を使うことで、エイリアス付きの複雑な置換もシンプルに書ける
- **`base_url` 引数**を持たせることで、サブディレポジトリへの移行など実用的なケースに対応できる
- **変換スクリプトは「ワンショット」**として割り切り、使い終わったらリポジトリから削除する也是一种の設計判断

Pythonの `re` モジュールは少しの工夫で強力なテキスト処理を可能にします。TDDのサイクル（テストを書く → 実装する）を回すことで、初心者の方でもバグの少ない堅牢なスクリプトを書けるようになります。ぜひご自身の環境でも試してみてください。