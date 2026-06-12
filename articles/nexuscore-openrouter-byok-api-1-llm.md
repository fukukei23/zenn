---
title: "【NexusCore事例】OpenRouter BYOK対応：ユーザーAPIキー1本드로マルチLLMを実現するまで"
emoji: "📝"
type: "tech"
topics: ["FastAPI", "OpenRouter", "APIキー管理", "セキュリティ", "LLM"]
published: false
---

```markdown
---
title: "【NexusCore事例】OpenRouter BYOK対応：ユーザーAPIキー1本でマルチLLMを実現するまで"
emoji: "🔑"
type: "tech"
topics: ["FastAPI", "OpenRouter", "APIキー管理", "セキュリティ", "LLM"]
published: false
---

## はじめに

近年、ChatGPTやClaude、Geminiなど、さまざまなLLM（大規模言語モデル）が登場し、開発現場でも用途に応じて複数のモデルを使い分けることが当たり前になりつつあります。

しかし、複数のLLMを利用しようとすると、各プロバイダーごとにAPIキーを取得・管理しなければならず、システム側の実装も煩雑になります。そこで今回は、オープンソースプロジェクト「**NexusCore**」の実装事例を基に、**OpenRouter**というサービスと**BYOK（Bring Your Own Key）**という仕組みを活用し、「ユーザーのAPIキー1本で複数のLLMを切り替えられるシステム」の作り方を解説します。

FastAPIを用いたバックエンドのセキュアなAPIキー管理から、Gradioを用いた画面UIの実装まで、具体的なコードとともに紹介します。

## OpenRouter BYOKとは？

そもそもOpenRouterは、さまざまなLLMを統一されたAPIフォーマットで利用できるプロキシサービスです。

通常はOpenRouterが提供するAPIキーを使って課金・利用しますが、**BYOK（Bring Your Own Key）**機能を利用することで、ユーザー自身が各LLMプロバイダー（OpenAIやAnthropicなど）と契約しているAPIキーを登録し、OpenRouterの便利なルーティング機能だけを利用することができます。

この仕組みをアプリケーションに組み込むことで、ユーザーはアプリ側に自分のAPIキーを預けるだけで、システム内のあらゆるLLM機能をシームレスに利用できるようになります。

## セキュアなAPIキー管理の実装

ユーザーのAPIキーを取り扱う上で最も重要なのが**セキュリティ**です。NexusCore（FastAPI）では、情報漏洩を防ぐための厳格な管理を実装しています。

### 1. 暗号化保存とFail-Closedの原則

APIキーをデータベースに平文（そのままの文字列）で保存するのは論外です。NexusCoreでは、環境変数 `NEXUS_ENCRYPTION_KEY` を使ってAPIキーを暗号化して保存します。

ここで重要なのが「**Fail-Closed（安全な方向への失敗）**」という設計です。システムが暗号化キーを見つけられなかった場合、エラーを無視して平文で保存するのではなく、**明確にエラーを返して保存を拒否**します。

以下は、暗号化と保存のバリデーションを実装したPythonコードの例です。

```python
import os
from cryptography.fernet import Fernet
from fastapi import HTTPException

def get_fernet_client() -> Fernet:
    """環境変数から暗号化キーを取得する"""
    key = os.getenv("NEXUS_ENCRYPTION_KEY")
    
    # Fail-Closed: 暗号化キーが未設定の場合は保存を拒否する
    if not key:
        raise HTTPException(
            status_code=500, 
            detail="Encryption key is not configured. API key cannot be saved."
        )
    return Fernet(key.encode())

def encrypt_api_key(api_key: str) -> str:
    """APIキーを暗号化して返す"""
    fernet = get_fernet_client()
    encrypted_key = fernet.encrypt(api_key.encode())
    return encrypted_key.decode()

def save_user_api_key(user_id: str, raw_api_key: str):
    """ユーザーのAPIキーを暗号化して保存する"""
    try:
        encrypted = encrypt_api_key(raw_api_key)
        # DBへの保存処理 (例: db.save(user_id, encrypted))
        print(f"Key for {user_id} securely saved.")
    except HTTPException:
        # 暗号化キーがない場合はここで処理を中断
        raise
```

### 2. ログからの情報漏洩防止

システムにエラーが起きた際、デバッグのために例外の詳細をログに出力することがあります。しかし、APIキーの登録処理などでエラーが発生した場合、スタックトレースにAPIキーそのものや機密情報が含まれてしまうリスクがあります。

NexusCoreの開発では、`openrouter_key` APIのログから例外の詳細を除去する修正を行いました。ユーザーには「エラーが発生した」ことだけを伝え、サーバーのログにも機密情報が書き出されないように設計しています。

## UIとテストによる品質担保

### Gradioを用いた設定画面の提供

セキュリティを高めても、ユーザーが使いにくければ意味がありません。NexusCoreでは、Pythonで手軽にWeb UIを作れる **Gradio** を利用して、OpenRouter BYOKの設定画面（`/settings/`）を実装しました。

ユーザーはブラウザ上で設定画面を開き、自身のAPIキーをワンクリックで登録・更新できます。また、5つのプロファイル（用途に応じたLLMのプリセット）を追加し、画面上で簡単にモデルを切り替えられるようにしました。

### テストカバレッジの徹底強化

APIキーの管理や認証（Auth）に関わる機能は、エッジケースでのバグが致命的な問題に繋がります。NexusCoreの開発では、以下の領域のテストカバレッジを80%台から95%以上に引き上げる取り組みを行いました。

- **認証フォールバック**: JWT認証が利用できない環境でのフォールバック処理
- **APIキーのルーティング**: DBが未初期化の場合のエラーハンドリング
- **予期しない例外ハンドラ**: 不正なフォーマットでのリクエスト時の挙動

特に、新規で36のテストを追加し、既存の1391のテスト全てが通ることを確認するなど、安全性を担保しながら機能追加を行っています。

## おわりに

ユーザーのAPIキー1本で複数のLLMをシームレスに切り替えられる体験は、AIを活用するアプリケーションのUXを大きく向上させます。

しかし、その裏では「ユーザーのAPIキーを絶対に漏らさない」という強い意志と、環境変数による暗号化（Fail-Closed）、ログのマスキング、そして徹底したテストによる品質担保が不可欠です。

FastAPIとOpenRouterを組み合わせたBYOK対応は、セキュアでマルチモデルなAIアシスタントを構築する上で非常に参考になるパターンの一つです。本記事が、皆さんのシステム設計とセキュリティ実装のヒントになれば幸いです。
```