---
title: "【GAS商用事例】本番運用で踏み抜いた5つの落とし穴と恒久対策"
emoji: "🕳️"
type: "tech"
topics: ["GAS", "Google Apps Script", "LINE Bot", "商用運用", "DoGet"]
published: false
---

## はじめに

GAS（Google Apps Script）+ Cloudflare Workers + LINE Messaging APIで構築した予約管理ボットを、実際にお客様が利用する商用環境として運用しています。開発中のローカルテストでは問題なく動いていたのに、本番デプロイ後に初めて発覚する「GAS Web App特有の落とし穴」がいくつもありました。

本記事では、その中から特に被害が大きかった（あるいは潜在していた）5つの落とし穴を、「何が起きたか → なぜ起きたか → 恒久対策」の形式で紹介します。GASでWebhookや管理APIを作ろうとしている方の、事前の地図になれば幸いです。

## セクション1: レスポンスAPIの罠（落とし穴①②）

### ① TextOutputにsetStatusCodeは存在しない

認証エラー時に401を返そうとして、次のようなコードを書いていました。

```typescript
// ❌ 動かないコード: TextOutput に setStatusCode は存在しない
function doGet(e: GoogleAppsScript.Events.DoGet) {
  if (!isValidToken(e.parameter.token)) {
    return ContentService
      .createTextOutput("Unauthorized")
      .setMimeType(ContentService.MimeType.TEXT)
      .setStatusCode(401); // ← ここで TypeError がスローされる
  }
  // ...正常処理
}
```

Node.jsやCloudflare Workersと同じ感覚で書いたのが敗因です。GASの`ContentService`が返す`TextOutput`には、HTTPステータスコードを設定するAPIが**そもそも存在しません**。その結果、本来401を返すべき経路で例外が発生し、エラーハンドリングが二重に崩れる事態になりました。

**恒久対策**はシンプルで、`setStatusCode`の呼び出しを全削除し、ステータスはボディのJSONで表現することです。HTTPステータスはほぼ200固定だと割り切り、外部監視やクライアントはボディの`error`フィールドで判定します。

### ② エラー時もHTMLではなくJSONを返す

GAS Web Appは未処理例外をHTML形式のエラーページとして返します。JSONパースを前提としたクライアントや死活監視はこれで壊れます。全ルートを`try/catch`で囲み、異常系でも必ずJSONを返す規約に統一しました。

## セクション2: 認証トークンの罠（落とし穴③④）

### ③ ADMIN_TOKEN未設定時は「全員拒否」にする

管理用トークン（ADMIN_TOKEN）をスクリプトプロパティに設定し忘れたままデプロイすると、`undefined`との比較になり、挙動が不定になります。レビューで合意を得た恒久対策は「**未設定なら503相当で全拒否**」です。

```typescript
const ADMIN_TOKEN = PropertiesService
  .getScriptProperties()
  .getProperty("ADMIN_TOKEN");

function checkAdmin(provided: string | undefined) {
  if (!ADMIN_TOKEN) {
    console.error("ADMIN_TOKEN is not configured");
    return { ok: false, error: "service_unavailable" }; // 503相当
  }
  if (!provided || !timingSafeEqual(provided, ADMIN_TOKEN)) {
    return { ok: false, error: "unauthorized" };
  }
  return null; // 認証OK
}
```

設定漏れのまま「たまたま動く」より、明確に fail-fast する方が商用では安全です。

### ④ トークン比較はtiming-safeに

`===`での文字列比較は先頭から順に照合し、不一致の時点で処理を打ち切るため、応答時間の差からトークンの先頭文字を推測されるリスクがあります（タイミング攻撃）。XORで全文字を比較する実装に置き換えました。

```typescript
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}
```

長さが異なる場合は早期リターンしますが、トークン長は公開情報ではないため許容できるトレードオフと判断しました。

## セクション3: 継続運用の罠（落とし穴⑤）

### ⑤ トリガー登録は冪等に、死活は外部から監視する

日次レポートを送る`sendDaily`を時間主導型トリガーで実行する際、デプロイのたびに`ScriptApp.newTrigger()`を呼ぶと**トリガーが重複登録され、同じ処理が複数回走ります**。そこで、登録済みかを確認してから作る冪等な登録関数を用意しました。

```typescript
function registerHeartbeatTrigger(): void {
  const handler = "sendDaily";
  const exists = ScriptApp.getProjectTriggers().some(
    (t) => t.getHandlerFunction() === handler
  );
  if (exists) {
    console.log(`trigger for ${handler} already exists. skip.`);
    return;
  }
  ScriptApp.newTrigger(handler).timeBased().everyDays(1).atHour(9).create();
}
```

さらに、GAS側のトリガー自体が止まっていないかを、5分間隔の外部プローブ（UptimeRobot等の死活監視サービス）で常時確認する体制にしました。監視対象のエンドポイントはボディのJSONで正常性を返す設計に統一しています。**「トリガーが登録済みであること」と「トリガーが実際に発火していること」は別物**であり、後者は外部からしか検証できません。

## おわりに

5つの落とし穴を振り返ると、共通する教訓は「**GAS Web Appは普通のHTTPサーバーではない**」ということに尽きます。ステータスコードは制御できない、例外はHTMLで返る、トリガーは冪等性を持たない──これらを早い段階で規約として固定しておくことが、商用運用の品質を左右します。

今回の対応はすべて自分のリポジトリのコミットログと運用ドキュメントに残しており、レビューでの指摘（複数レビュアーの合意で採用した修正も多くあります）も恒久対策に反映済みです。GASでの本番運用を検討している方は、ぜひデプロイ前にこの5点をチェックしてみてください。