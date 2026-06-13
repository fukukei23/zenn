---
title: "【初心者向け】fail-closed設計で学ぶ 安全性の低いコードが如何に危険か"
emoji: "🔒"
type: "tech"
topics: ["セキュリティ", "failclosed", "Python", "初心者向け"]
published: false
---

# はじめに

公務員からIT業界に転職した私が、実務で最も衝撃を受けた概念の一つが **「fail-closed（フェイルクローズド）設計」** です。

公務員時代の私は「エラーが出てもとりあえず動くならOK」という感覚でシステムに向き合っていました。しかし実際の開発現場では、**エラー時にどう振る舞うか**が性命に関わります。

本記事では、私が開発に参加しているプロジェクト [NexusCore](https://github.com/user/nexuscore) で実際に実装した **「暗号化キー未設定時は保存を拒否する」** というfail-closed設計を題材に、安全なデフォルト設定の重要性を具体的なコード例で解説します。

:::message
この記事は、セキュリティの専門家向けではなく、**駆け出しエンジニアや、セキュリティ設計に馴染みのない方**を対象にしています。「なんとなく危ないのは分かるけど、具体的にどう書けばいいの？」という方の参考になれば幸いです。
:::

---

# fail-openとfail-closed — エラー時にどう動くか

## fail-open（危険な設計）

**fail-open** は、エラーが発生した際に**処理を継続**する設計です。アクセス制御で認証サーバーが落ちたら「とりあえず通す」のが典型的な例です。

一見「親切」に見えますが、攻撃者にとっては絶好のチャンスです。

```python
# ❌ fail-openの例：暗号化キーがなくても平文で保存してしまう
def save_secret(key_store, data):
    try:
        encrypted = encrypt(data, key_store.get_encryption_key())
    except Exception:
        # キーがなくてもとりあえず保存...
        encrypted = data  # 平文で保存！
    
    key_store.save(encrypted)
```

「動くからヨシ」となりがちですが、**暗号化キーが未設定の環境で機密データが平文保存される**という致命的な脆弱性になります。

## fail-closed（安全な設計）

**fail-closed** は、エラーが発生した際に**処理を拒否**する設計です。何かがおかしいなら、安全な方向に倒して止めます。

```python
# ✅ fail-closedの例：暗号化キーがなければ保存を拒否
def save_secret(key_store, data):
    encryption_key = key_store.get_encryption_key()
    
    # キーが未設定なら保存を拒否する
    if not encryption_key:
        raise ValueError(
            "NEXUS_ENCRYPTION_KEY is not set. "
            "Refusing to save unencrypted data."
        )
    
    encrypted = encrypt(data, encryption_key)
    key_store.save(encrypted)
```

**エラーで止まることは悪いことではありません。黙って脆弱な状態で動き続けることの方が、遥かに危険です。**

---

# NexusCoreでの実装例

## 実際のコミット

NexusCoreでは、OpenRouter BYOK（Bring Your Own Key）機能の実装に伴い、APIキーを安全に保存する仕組みが必要になりました。

その際、以下のコミットでfail-closed設計を導入しました。

> `fix: key_store fail-closed — NEXUS_ENCRYPTION_KEY未設定時は保存拒否`

このコミットの核心は非常にシンプルです。

```python
class KeyStore:
    """APIキーの安全な保存を担うクラス"""
    
    def __init__(self):
        self._encryption_key = os.environ.get("NEXUS_ENCRYPTION_KEY", "")
    
    def save(self, key_id: str, secret: str) -> None:
        """秘密鍵を暗号化して保存する
        
        NEXUS_ENCRYPTION_KEYが未設定の場合は
        保存を拒否し、平文での保存を防ぐ（fail-closed）
        """
        if not self._encryption_key:
            raise EncryptionKeyNotSetError(
                "NEXUS_ENCRYPTION_KEY is not configured. "
                "Cannot save secrets safely. "
                "Set the environment variable before proceeding."
            )
        
        encrypted = self._encrypt(secret, self._encryption_key)
        self._store[key_id] = encrypted
```

`NEXUS_ENCRYPTION_KEY` 環境変数が空文字列または未設定の場合、`EncryptionKeyNotSetError` を送出して保存を拒否します。

## なぜここで止めるのか

「デプロイ時に環境変数を設定し忘れたら？」という疑問を持つかもしれません。

実際の運用では、次のようなシナリオが考えられます：

- ローカル開発環境で `.env` を設定し忘れる
- ステージング環境のコンテナ再ビルド時に環境変数が欠落する
- CI/CDパイプラインの設定ミスで本番環境に空の変数が渡る

いずれの場合も、**fail-openなら気づかずに平文が保存され続けます**。fail-closedなら即座にエラーで気づけます。

:::message alert
**早く壊れる（Fail Fast）ことは、セキュリティにおいて最も望ましい振る舞いです。** 本番環境で数ヶ月間平文が保存され続けてから発覚するより、開発環境で即座にエラーになる方が圧倒的にマシです。
:::

---

# もう一つの教訓 — ログからの情報漏洩防止

同じ時期に、NexusCoreでは別のセキュリティ修正も行いました。

> `fix: openrouter_key APIのログから例外詳細を除去（情報漏洩防止）`

これはfail-closedとは少し異なる教訓ですが、併せて知っておくべき重要なポイントです。

```python
# ❌ 危険なログ出力
import logging

logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def handle_error(request, exc):
    # 例外の詳細をそのままログに出力
    logger.error(f"API error: {exc}")  # スタックトレースにAPIキーが含まれる可能性
    return JSONResponse(status_code=500, content={"detail": str(exc)})
```

```python
# ✅ 安全なログ出力
import logging
import hashlib

logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def handle_error(request, exc):
    # ユーザーには汎用的なメッセージのみ返す
    logger.error(f"API error occurred. Type: {type(exc).__name__}")
    return JSONResponse(
        status_code=500, 
        content={"detail": "Internal server error"}
    )
```

例外の `str(exc)` をそのままレスポンスやログに書き出すと、APIキーやトークンが漏洩するリスクがあります。エラーメッセージは **必要最小限** に留めるべきです。

---

# 実務で学んだ3つの教訓

公務員からIT転職して2年、セキュリティに関するコードレビューを重ねて学んだことを3つにまとめます。

## 1. デフォルトは最も厳しく

設定が漏けていた場合のデフォルトの動作は、**最も厳しい（最も制限の強い）状態**であるべきです。「設定されていれば緩める」という方向で設計します。

```
# 思考の方向性
❌ 「設定されていなければ緩くする」
✅ 「設定されていなければ厳しくする」
```

## 2. エラーは味方

動かないことは悪いことではありません。**間違った状態で動き続けること**こそが最悪の事態です。テストカバレッジを上げるのも、この「間違った状態」に早く気づくためです。

NexusCoreでも認証周りのテストカバレッジを 82% → 95%+ に向上させる取り組みを並行して進めていました。

> `test: api/auth.py JWT認証フォールバック カバレッジ向上（82%→95%+）`

## 3. 「動いた」で終わらない

機能が動作することと、安全に動作することは別の問題です。コードレビューでは以下の問いを常に意識するようにしています：

- エラー時に情報は漏れないか？
- 認証が失敗した場合、どう振る舞うか？
- 設定が欠落した場合、安全側に倒れているか？

---

# おわりに

fail-closed設計は、教科書には一行で書かれているかもしれないシンプルな概念ですが、実装レベルで徹底するには意識的な努力が必要です。

NexusCoreの実装では、環境変数一つの未設定を見逃さないためにfail-closedを採用しました。結果として、**開発環境での設定ミスを即座に検知**でき、本番環境でのインシデントを未然に防ぐことができています。

セキュリティは、特別なツールや高価な製品だけで実現するものではありません。**日々のコードの一つ一つの分岐で、着実に積み上げるもの**です。

この記事が、これからセキュリティを学ぶ方の「具体的な一歩」になれば嬉しいです。

---

**参考リンク**
- [NexusCore リポジトリ](https://github.com/user/nexuscore)
- [OpenRouter BYOK セットアップガイド](https://github.com/user/nexuscore/blob/main/docs/byok-setup.md)

最後まで読んでいただき、ありがとうございました。ご質問やご意見があれば、コメント欄でお気軽にどうぞ 🙌