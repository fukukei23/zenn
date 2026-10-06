---
title: 整形外科予約ボット設計入門：GAS×Cloudflare Worker×Stripeで学ぶマルチサービス連携
emoji: 🏥
type: tech
topics:
  - GAS
  - CloudflareWorkers
  - Stripe
  - LINE
  - Webhook
published: false
---

## はじめに

地域の整形外科クリニックで「予約の受付が電話のみで、開院直後は電話がパンクする」という課題を聞き、LINEで完結する予約ボット（プロジェクト名： reserve-optimizer）を作りました。要件は次の4点です。

- 患者さんはLINEで日時を選ぶだけ（電話不要）
- 無断キャンセル対策として、保証金を事前決済
- 事務の方は使い慣れたスプレッドシートの台帳を確認するだけ
- 月額の運用コストはほぼゼロ

GAS・Cloudflare Worker・Stripeという性質の異なるサービスを組み合わせたので、「**どの処理をどのサービスに担わせるか**」という設計判断を中心に解説します。

## 全体アーキテクチャ：役割分担をどう決めたか

全体の流れはシンプルな一方通行にしました。

```text
① 患者がLINEで操作 → LINEプラットフォームがGASにwebhook
② GASがスプレッドシート台帳を更新（会話状態・予約枠の仮押さえ）
③ GAS → Cloudflare Worker → Stripe で決済セッションを作成し、URLをLINEで返信
④ 決済完了 → StripeがWorkerにwebhook → WorkerがGASに通知 → 台帳を「予約確定」へ
```

各サービスの採用理由は次の通りです。

- **GAS**: LINEのwebhook受信と会話管理、FAQ自動応答（LLM API呼び出し）を担当。医院がGoogle Workspaceを使っていたため、台帳をそのままスプレッドシートに置くと「プログラムが壊れても記録は残る」状態にできるのが大きかった
- **Cloudflare Worker**: 決済APIの呼び出しとwebhook処理だけを担当。StripeのシークレットキーはWorkerのSecretsに置き、GAS側に秘密情報を持ち込まない設計にした
- **Stripe Checkout**: ホスト型の決済ページなのでカード情報を自サーバーで扱わない。小さなシステムではこの点が最重要

「GASだけで完結させない」のがポイントです。GASでも決済は組めますが、秘密情報の管理とwebhookの署名検証（`crypto.subtle`の有無）の観点でWorkerに分ける判断をしました。

## 会話UI：ステートマシンとQuickReply

会話は「日付選択 → 時間帯 → 診療内容 → 確認 → 決済」のステートマシンです。状態は台帳シートの1行（LINEユーザーIDがキー）に保持し、GASはメッセージを受信するたびに「今どの状態か」を読んで次の返信を組み立てます。

整形外科は高齢の患者さんが多いため、自由入力を排除してすべてQuickReply（選択ボタン）で進めます。実運用でわかったのは、ボタンは最大13個まで置けるものの、**4〜6個に絞るほうが押し間違いが激減した**ことです。

```typescript
// QuickReplyメッセージの組み立て（GAS側・LineService.jsより抜粋）
function sendLineReplyQuickReply(replyToken, text, quickReplies) {
  var message = {
    type: 'text',
    text: text,
    quickReply: {
      items: quickReplies.map(function(qr) {
        return {
          type: 'action',
          action: {
            type: 'message',   // ボタン押下で固定テキストを送信させる
            label: qr.label,   // ボタンに表示される文字
            text: qr.text      // 押した時にユーザーから送られるテキスト
          }
        };
      })
    }
  };
  return sendLineMessages(replyToken, [message]);
}
```

ボタンの `text` には「明日の午前」のような確定語を入れ、患者さんが押すだけで会話が1ステップ進むようにします。自由入力が来た場合はステートマシン側で受け止めて「ボタンから選んでください」と再案内する二段構えです。

## webhookの署名検証：Workerに集約した1点張り

LINEとStripeはどちらもwebhookに署名（HMAC）を付けてくるため、受信側で必ず検証します。この検証をWorker側に集約したのが、冒頭の「GASに秘密情報を持ち込まない」設計の効きどころです。

```typescript
// Worker側（index.tsより抜粋・イメージ）
const isValid = await verifyLineSignature(body, signature, env.LINE_CHANNEL_SECRET);
if (!isValid) {
  return new Response("Invalid signature", { status: 401 });
}
// LINE に即座に 200 OK を返す（タイムアウト回避）
// GAS 転送は waitUntil でバックグラウンド実行
ctx.waitUntil(forwardToGAS(body, env, "line"));
```

ポイントは2つです。

- **検証を通ったら即200を返し、GASへの転送はバックグラウンド（`waitUntil`）に回す**。webhook送信元はタイムアウトでリトライしてくるため、遅い下流に引きずられて多重送信になるのを防ぐ
- **Stripe → Worker の転送は最小データだけに絞る**（イベント種別・決済ID・`metadata` の予約ID）。URL長制限と不要情報流出の両面で、転送経由のデータは小さいほど安全

## おわりに

「どのサービスに何を担わせるか」を先に決めてから書き始めたことで、実装中の迷いはほぼありませんでした。

- 状態と台帳 = **スプレッドシート**（壊れても記録が残る・事務がそのまま読める）
- 秘密情報とwebhook検証 = **Cloudflare Worker**（GASのサンドボックスの制約を回避）
- カード情報 = **Stripe Checkout に丸投げ**（自前で一切触らない）

小さな業務システムでは「全部 GAS で済ませる」のが一見楽ですが、秘密情報の置き場所とwebhookの署名検証という2点だけで外に出す判断ができます。同じ課題（電話予約のパンク・事務の負担）を抱える医院さんの一助になれば幸いです。
