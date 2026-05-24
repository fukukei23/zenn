---
title: "LINE Bot × Stripe × Cloudflare Workers で予約システムを2週間で作った話"
emoji: "📅"
type: "tech"
topics: ["linebot", "stripe", "cloudflareworkers", "gas", "typescript"]
published: false
---

## はじめに

予約管理システムが必要になりました。LINE Botで予約を受けて、Stripeで決済して、Cloudflare WorkersでWebhookを受ける——この3層構成を2週間で作りました。

本記事では、**reserve-optimizer** の設計と、各技術の選定理由・実装のポイントを解説します。

## アーキテクチャ

```
[LINEユーザー]
     ↓ メッセージ
[Cloudflare Worker]  ← リバースプロキシ
     ↓ 転送
[GAS Web App]        ← ビジネスロジック
     ↓ 読み書き
[Google Sheets]      ← データストア
     ↑ Webhook
[Stripe]             ← 決済
```

**なぜこの構成か**:
- **Cloudflare Workers**: LINE WebhookのHTTPS必須要件を満たす（GAS単体だと遅い）
- **GAS**: サーバー不要・無料枠で運用・Google Sheetsとシームレス
- **Stripe**: PCI DSS準拠（カード情報を自システムに持たない）

## 実装のポイント

### 1. LINE Webhook署名検証（タイミングセーフ）

```javascript
// WebhookRouter.js — タイミング攻撃を防ぐ署名検証
function verifyLineSignature(body, signature) {
    const key = CryptoJS.enc.Base64.parse(getChannelSecret());
    const hash = CryptoJS.HmacSHA256(body, key);
    const expected = CryptoJS.enc.Base64.stringify(hash);

    // ❌ 普通の比較（タイミング攻撃に脆弱）
    // return expected === signature;

    // ✅ 定数時間比較
    return constantTimeCompare(expected, signature);
}
```

**タイミング攻撃**: 文字列比較の処理時間から署名を推測する攻撃。`===` ではなく定数時間比較を使う必要があります。

### 2. Stripe Webhook署名検証（冪等性付き）

```javascript
// StripeWebhookHandler.js
function verifyStripeSignature(payload, sigHeader) {
    const event = stripe.webhooks.constructEvent(
        payload, sigHeader, getWebhookSecret()
    );

    // タイムスタンプ検証（5分以内）
    const tolerance = 300; // seconds

    // 冪等性チェック（20分間キャッシュ）
    const cacheKey = `stripe_${event.id}`;
    if (CacheService.getScriptCache().get(cacheKey)) {
        return { status: 'duplicate', event: null };
    }
    CacheService.getScriptCache().put(cacheKey, 'processed', 1200);

    return { status: 'ok', event };
}
```

**冪等性**: Stripeは同じイベントを複数回送信することがある。CacheService（20分TTL）で重複排除。

### 3. Cloudflare Workers（リバースプロキシ）

```typescript
// worker.ts — パスベースルーティング
export default {
    async fetch(request: Request): Promise<Response> {
        const url = new URL(request.url);

        if (url.pathname === '/webhook/line') {
            return forwardToGAS(request, 'line');
        }
        if (url.pathname === '/webhook/stripe') {
            return forwardToGAS(request, 'stripe');
        }
        if (url.pathname === '/health') {
            return new Response('ok');
        }
        return new Response('Not Found', { status: 404 });
    }
};
```

**最小転送**: Workersは受信したパラメータをURLエンコードしてGASに転送。ペイロードの再構築を最小化。

### 4. 決済フロー

```
LINE Bot「予約確定」ボタン
  → Stripe Checkout Session 作成
  → 決済URL を LINE で送信
  → ユーザーがカード入力
  → Stripe Webhook で決済完了通知受信
  → Google Sheets のステータス更新
```

**Stripe Checkout** を使用する理由: カード情報を自システムに一切持たない。PCI DSSの対象外。

## Google Sheets を DB 代わりに使う工夫

### ないものは作る

```javascript
// シートを行オブジェクトとして扱うユーティリティ
function findByColumn(sheet, column, value) {
    const data = sheet.getDataRange().getValues();
    for (let i = 1; i < data.length; i++) {
        if (data[i][column] === value) return i;
    }
    return -1;
}
```

### 認証（簡易）

```javascript
// Bearer token によるエンドポイント認証
function doGet(e) {
    const token = e.parameter.token;
    if (token !== getAutopilotToken()) {
        return ContentService.createTextOutput('Unauthorized');
    }
    // ... 処理
}
```

## 苦労した点

### GASの制約
- **実行時間上限6分**: 長い処理は分割する必要がある
- **同時実行制限**: 複数Webhookが同時到着時にキューイングが必要
- **スクリプトプロパティ**: シークレットの保存先（暗号化済み）

### Cloudflare Workers の制約
- **リクエストサイズ上限**: LINE画像メッセージ等はURLのみ転送
- **実行時間上限30秒**: GAS側の処理が重い場合はタイムアウト

### Stripe Checkout の注意点
- **セッション有効期限**: 24時間（デフォルト）。予約システムでは48時間に延長
- **通貨設定**: `currency: 'jpy'` を忘れがち

## セキュリティ対策

| 対策 | 実装状況 |
|------|---------|
| LINE Webhook署名検証 | ✅ HMAC-SHA256 + タイミングセーフ |
| Stripe Webhook署名検証 | ✅ 署名 + タイムスタンプ + 冪等性 |
| カード情報非保持 | ✅ Stripe Checkout使用 |
| APIキー管理 | ✅ ScriptProperties（暗号化） |
| レート制限 | ❌ 今後対応 |

## コード

https://github.com/fukukei23/reserve-optimizer

---

*この記事はClaude Code（GLM-5.1）と一緒に書きました。*
