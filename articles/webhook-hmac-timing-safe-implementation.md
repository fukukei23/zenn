---
title: "Webhook署名検証をタイミングセーフ比較で実装した話"
emoji: "🔏"
type: "tech"
topics: ["security", "webhook", "hmac", "gas"]
published: false
---

## はじめに

Webhookの署名検証で `===` を使っていませんか？ それ、**タイミング攻撃**に脆弱かもしれません。

本記事では、HMAC-SHA256署名検証を**タイミングセーフ比較**で実装する方法を解説します。

## タイミング攻撃とは

文字列比較の**処理時間の差**から、正しい署名を推測する攻撃:

```python
# ❌ タイミング攻撃に脆弱
def verify(signature, expected):
    return signature == expected
    # 1文字目が違う → 即false（速い）
    # 5文字目まで一致 → 5文字目でfalse（遅い）
    # 攻撃者は処理時間から文字を1つずつ特定できる
```

```
試行1: "aXXXXXXXX" → 0.001ms（1文字目不一致）
試行2: "bXXXXXXXX" → 0.002ms（1文字目一致、2文字目不一致）
試行3: "bCXXXXXXX" → 0.003ms（2文字まで一致）
...
```

## 実装: Google Apps Script（JavaScript）

```javascript
// WebhookRouter.js
function verifyLineSignature(body, signature) {
    const channelSecret = getChannelSecret();
    const key = CryptoJS.enc.Base64.parse(channelSecret);
    const hash = CryptoJS.HmacSHA256(body, key);
    const expected = CryptoJS.enc.Base64.stringify(hash);

    // ✅ 定数時間比較
    return constantTimeCompare(expected, signature);
}

function constantTimeCompare(a, b) {
    if (a.length !== b.length) return false;
    let result = 0;
    for (let i = 0; i < a.length; i++) {
        result |= a.charCodeAt(i) ^ b.charCodeAt(i);
    }
    return result === 0;
}
```

**ポイント**: 全文字を必ず比較し、結果はXORの累積で判定。途中でリターンしない。

## 実装: Python版

```python
import hmac
import hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    # ✅ hmac.compare_digest は定数時間比較
    return hmac.compare_digest(expected, signature)
```

Pythonには `hmac.compare_digest` が標準ライブラリにあります。

## Stripe Webhookの実装（タイムスタンプ検証付き）

```javascript
function verifyStripeWebhook(payload, sigHeader) {
    const secret = getWebhookSecret();
    const parts = sigHeader.split(',');

    let timestamp = '';
    let signature = '';
    for (const part of parts) {
        const [key, value] = part.split('=');
        if (key === 't') timestamp = value;
        if (key === 'v1') signature = value;
    }

    // タイムスタンプ検証（5分以内）
    const currentTime = Math.floor(Date.now() / 1000);
    if (Math.abs(currentTime - parseInt(timestamp)) > 300) {
        return false;
    }

    // 署名検証
    const signedPayload = `${timestamp}.${payload}`;
    const expected = CryptoJS.HmacSHA256(signedPayload, secret);
    const expectedSig = CryptoJS.enc.Hex.stringify(expected);

    return constantTimeCompare(expectedSig, signature);
}
```

**タイムスタンプ検証**: リプレイ攻撃を防ぐ。5分以内のイベントのみ受け付ける。

## テスト

```python
def test_webhook_signature_valid():
    payload = b'{"event": "test"}'
    secret = "webhook_secret"
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_webhook(payload, sig, secret) is True

def test_webhook_signature_invalid():
    assert verify_webhook(b'test', 'invalid_sig', 'secret') is False

def test_webhook_timing_safe():
    # 処理時間が一定であることを確認（簡易）
    import time
    times = []
    for _ in range(100):
        start = time.perf_counter()
        verify_webhook(b'test', 'a' * 64, 'secret')
        times.append(time.perf_counter() - start)
    # 分散が小さいことを確認
    assert max(times) - min(times) < 0.001
```

## まとめ

| 実装 | 言語 | メソッド |
|------|------|---------|
| LINE Webhook | GAS（JS） | CryptoJS.HmacSHA256 + custom constantTimeCompare |
| Stripe Webhook | GAS（JS） | CryptoJS.HmacSHA256 + タイムスタンプ検証 |
| 汎用 | Python | hmac.compare_digest |

**`===` ではなく、必ずタイミングセーフ比較を使いましょう。**

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
