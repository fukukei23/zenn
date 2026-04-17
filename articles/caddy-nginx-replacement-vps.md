---
title: "「nginx書けない人に送るCaddy最強設定」〜VPS AIエージェントの本番構成晒し〜"
emoji: "🍔"
type: "tech"
topics: ["caddy", "docker", "vps", "ai", "インフラ"]
published: true
---

## はじめに：nginxの設定ファイル、読めますか？

VPSを借りて、いざ自分の作ったAIエージェントを公開しようとしたとき、多くの人が「リバースプロキシ」という壁にぶつかります。

ググって出てくるのはnginxの設定ファイルです。

```nginx
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**「長くない？」「SSLの設定だけで何行あるの？」「証明書の更新はどうするの？」**

こんな疑問を持ったあなたに、強烈にお勧めするのが**Caddy**です。

今回は、VPS上でAIエージェントをホストする際の「Caddyを使った本番構成」を余すことなく全公開します。コピペですぐに動く設定ファイル付きです。

## Caddyとは？〜Auto HTTPSの魔法〜

Caddyは、Go言語で書かれたモダンなWebサーバーです。最大の特徴は**Auto HTTPS**。

ドメイン名を設定ファイルに書くだけで、以下の作業を**すべて全自動**で行ってくれます。

- Let's EncryptでのSSL証明書取得
- 証明書の自動更新（cron不要）
- HTTPからHTTPSへのリダイレクト

nginxであれば数行〜数十行書いていたSSL関連の設定が、Caddyでは**一切不要**になります。

## 全体アーキテクチャ図

今回構築する構成は以下の通りです。Docker Composeを使って、CaddyとAIエージェントを連携させます。

```text
[インターネット]
      |
      | (HTTPS: 443)
      |
+-----|-------------------------------+
|     V        VPS (UFWでポート制限)  |
|  +---------+                        |
|  | Caddy   | (Auto HTTPS & 認証)    |
|  +---------+                        |
|     | (Docker Network)              |
|     V                               |
|  +---------+                        |
|  | AIエージェント | (ポート: 18789)   |
|  +---------+                        |
+-------------------------------------+
```

## Step 1: Docker ComposeでCaddy + アプリを立てる

まずは構成ファイルを作成します。ポイントは、AIエージェントのポートをローカルのみにバインドしている点です（これ、超重要です）。外部から直接アクセスされるのを防ぎます。

```yaml
services:
  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - openclaw-net

  openclaw-gateway:
    image: openclaw-custom:latest
    container_name: openclaw-gateway
    restart: unless-stopped
    env_file: .env
    volumes:
      - ~/.openclaw:/sandbox/.openclaw
    ports:
      - "127.0.0.1:18789:18789"  # ローカルのみバインド（超重要）
    networks:
      - openclaw-net
    init: true

networks:
  openclaw-net:
    ipam:
      config:
        - subnet: 172.30.0.0/24

volumes:
  caddy_data:
  caddy_config:
```

Caddyはデータの永続化のために `caddy_data` と `caddy_config` をボリュームにマウントしておきます。これでコンテナを再作成しても証明書が消えません。

## Step 2: Caddyfileを書く（3行でHTTPS + 認証付きリバースプロキシ）

nginxの複雑な設定が嘘のように、Caddyの設定は**わずか数行**で完了します。

AIエージェントを一般公開せず、BasicAuthでパスワード保護する構成です。

```caddyfile
fopenclaw.com {
    encode gzip

    basicauth {
        deployer $2a$14$HASHED_PASSWORD
    }

    reverse_proxy localhost:18789
}
```

これだけです。たったこれだけで、以下の要件がすべて満たされます。

- `fopenclaw.com` のSSL証明書自動取得・更新
- HTTPSへの強制リダイレクト
- gzipによる通信の圧縮
- BasicAuthによるパスワード保護
- AIエージェントへのリバースプロキシ（WebSocketのアップグレードにも自動対応）

## Step 3: BasicAuthでパスワード保護

BasicAuthのパスワードは平文ではなく、ハッシュ化したものを記述します。ハッシュの生成もDockerを使えば一発です。

以下のコマンドをターミナルで実行してください。

```bash
echo "あなたのパスワード" | docker run -i --rm caddy:2 hash-password
```

出力された `$2a$14$...` という文字列を、先ほどの `Caddyfile` の `HASHED_PASSWORD` の部分にコピペしてください。

## Step 4: UFWでポートを絞る

最後に、VPSのファイアウォール（UFW）を設定します。**ここを怠ると、CaddyをバイパスされてAIエージェントが直接攻撃される危険性があります。**

```bash
ufw default deny incoming
ufw allow 80/tcp
ufw allow 443/tcp
ufw limit 22/tcp
ufw deny 18789
ufw enable
```

- 80番と443番はCaddy用に許可
- 22番(SSH)は制限付きで許可（`limit`によりブルートフォース攻撃を防ぎます）
- 18789番は**外部からアクセスできないように明示的に拒否**

これで、外部からのアクセスは必ずCaddyを経由するようになり、安全な構成が完成しました。

## nginx vs Caddy 比較表

最後に、設定のしやすさを比較してみましょう。

| 比較項目 | nginx | Caddy |
| --- | --- | --- |
| **SSL証明書の取得** | Certbotの導入・実行が必要 | ドメインを書くだけ（全自動） |
| **証明書の更新** | Cron等で設定が必要 | 自動更新（設定不要） |
| **HTTPSリダイレクト** | `return 301 https://...` の記述が必要 | 自動でリダイレクト（記述不要） |
| **リバースプロキシ設定** | `proxy_set_header` 等の数行の記述が必要 | `reverse_proxy` の1行のみ |
| **WebSocket対応** | 別途 `Upgrade` ヘッダーの設定が必要 | 自動でよしなにしてくれる |
| **設定ファイルの行数** | 多くなりがち（20〜50行） | 非常にシンプル（3〜10行程度） |

## まとめ

nginxは非常に高機能で素晴らしいソフトウェアですが、「とりあえずVPSでAIエージェントをHTTPSで公開したい」という目的に対しては、オーバースペック気味であり設定の難易度も高いです。

Caddyを使えば、複雑な設定に悩まされることなく、**「ドメインとコンテナを繋ぐだけ」** で本番水準のセキュアな環境が作れます。

今回はAIエージェントをテーマにしましたが、どんなバックエンドアプリケーションにも適用できる強力な構成です。「nginxの設定ファイルが複雑すぎて挫折した」という方は、ぜひCaddyを試してみてください。その手軽さに驚くはずです。
