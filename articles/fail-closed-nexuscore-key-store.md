---
title: "【初心者向け】fail-closed設計をNexusCoreの実例で学ぶ：key_storeの安全実装"
emoji: "🔒"
type: "tech"
topics: ["Python", "セキュリティ", "failclosed", "NexusCore", "初心者向け"]
published: false
---

## はじめに

ソフトウェア開発において「エラーが起きたときにどう振る舞うか」を決めることは、システムの堅牢性において非常に重要です。

たとえば、ユーザーのAPIキーを暗号化してデータベースに保存する機能を実装するとします。もしシステムに必要な「暗号化用のキー」が設定されていなかった場合、あなたならどうしますか？

1. **とりあえず平文（暗号化なし）で保存して、システムは動かし続ける**
2. **保存処理を中断し、エラーとして扱う**

セキュリティを重視する設計では、間違いなく「2」を選びます。このように**「問題が発生した際、安全が確保できないなら処理を停止・拒否する」という設計思想を「fail-closed（フェイルクローズド）」**と呼びます。

本記事では、オープンソースプロジェクト「NexusCore」の実際のコミットを題材に、なぜfail-closed設計が重要なのか、そしてPythonでどのように実装するのかを初心者向けに解説します。

## fail-openとfail-closedの違い

まずは、エラー時の振る舞いにおける2つの考え方を理解しましょう。

### fail-open（フェイルオープン）
障害や設定不備が発生した際、**「機能は制限されるが、システム自体は動き続ける（門を開いたままにする）」**考え方です。
利便性や可用性（システムが止まらないこと）を重視しますが、セキュリティの穴になりやすいというリスクがあります。先ほどの例で言えば、「暗号化キーがないから、平文で保存しちゃおう」というのがfail-openです。

### fail-closed（フェイルクローズド）
障害や設定不備が発生した際、**「安全が保証できないなら、その処理は中止する（門を閉ざす）」**考え方です。
セキュリティを最優先するため、一時的に機能が使えなくなっても問題ないような場面で採用されます。

## NexusCoreにおけるkey_storeの実例

NexusCoreプロジェクトでは、OpenRouterというサービスのAPIキーをユーザー自身で登録・管理できる「BYOK（Bring Your Own Key）」機能が実装されました。このAPIキーはユーザーの重要なクレデンシャル（認証情報）であるため、データベースに保存する際は暗号化が必須です。

しかし、環境変数 `NEXUS_ENCRYPTION_KEY` が未設定のまま保存処理が走ってしまったらどうなるでしょうか？

NexusCoreのとあるコミット（`fix: key_store fail-closed — NEXUS_ENCRYPTION_KEY未設定時は保存拒否`）では、この問題に対してfail-closedアプローチで修正が行われました。

### ❌ 悪い例（fail-openになってしまっているコード）

初心者が陥りやすいのは、「とりあえずエラーを握りつぶして、平文で保存してしまう」というパターンです。

```python
import os

def save_api_key(user_id: str, api_key: str):
    encryption_key = os.getenv("NEXUS_ENCRYPTION_KEY")
    
    # キーがなくても、とりあえずシステムを動かしたい...
    if not encryption_key:
        print("Warning: Encryption key is missing. Saving without encryption.")
        encrypted_key = api_key # 平文のまま保存してしまう（超危険！）
    else:
        encrypted_key = encrypt(api_key, encryption_key)
        
    db.save(user_id, encrypted_key)
```

この実装では、システム自体はエラーで止まりませんが、データベース上に平文のAPIキーが散乱することになり、情報漏洩時の被害が甚大になります。

### ⭕ 良い例（fail-closedを取り入れた安全な実装）

fail-closedの思想に基づくと、「暗号化キーがない＝安全に保存できない＝保存を拒否する」というフローになります。

```python
import os
from cryptography.fernet import Fernet

class KeyStore:
    def __init__(self):
        # 暗号化キーを環境変数から取得
        self.encryption_key = os.getenv("NEXUS_ENCRYPTION_KEY")
        
        # fail-closed: キーが設定されていなければ、インスタンス化の段階で停止させる
        if not self.encryption_key:
            raise RuntimeError(
                "NEXUS_ENCRYPTION_KEY is not set. "
                "For security reasons (fail-closed), API key storage is disabled."
            )

    def save_api_key(self, user_id: str, api_key: str):
        # 初期化を通過しているため、ここでは安全に暗号化できる
        cipher_suite = Fernet(self.encryption_key)
        encrypted_key = cipher_suite.encrypt(api_key.encode('utf-8'))
        
        db.save(user_id, encrypted_key)
        return {"status": "success"}
```

このように実装することで、設定ミスがあったとしても「暗号化されない状態で保存される」ことは物理的に起こらなくなります。

## セキュリティをさらに強固にする：例外の取り扱い

fail-closed設計を採用してエラーを発生させる場合、**「エラーメッセージに何を含めるか」**にも気を配る必要があります。

実はNexusCoreの別のコミット（`fix: openrouter_key APIのログから例外詳細を除去（情報漏洩防止）`）では、このエラー処理時のログ出力に対するセキュリティ修正が行われています。

エラーが発生した際、スタックトレース（エラーの詳細な経緯）や内部のパスなどをそのままログやユーザーへのレスポンスに出力してしまうと、攻撃者にシステムの内部構造を漏洩させてしまう可能性があります。

```python
# ❌ 危険なログ出力（例外の詳細をそのまま表示）
try:
    key_store.save_api_key(user_id, raw_key)
except Exception as e:
    # ログやAPIのレスポンスに e（スタックトレースなど）を含めない！
    logging.error(f"Failed to save key: {e}")

# ⭕ 安全なログ出力
try:
    key_store.save_api_key(user_id, raw_key)
except Exception:
    # ユーザーには固定の安全なメッセージだけを返し、詳細は内部ログ（安全な場所）にのみ記録する
    logging.error("Failed to save API key due to a server error.")
    return {"error": "An internal error occurred. Please contact support."}
```

「システムを止める（fail-closed）」だけでなく、「止まった際の情報の出し方」まで配慮することで、真の安全なシステムを作ることができます。

## おわりに

今回はNexusCoreの実例をもとに、fail-closed設計の考え方とPythonでの実装例を解説しました。

- **fail-open**：エラー時に動き続けることを優先するが、セキュリティリスクが高まる
- **fail-closed**：エラー時に安全を優先し、処理を停止・拒否する

開発の現場では「例外が起きたらとりあえず `try-except` で括って動かす」というコードを書きがちです。しかし、認証やデータ保存など、セキュリティに関わる処理においては「**安全が確保できないなら、潔く失敗する**」というマインドセットを持つことが重要です。

皆さんもこれからコードを書く際、エラーハンドリングの分岐で「本当にそのまま処理を進けてよいのか？」を一度立ち止まって考えてみてください。