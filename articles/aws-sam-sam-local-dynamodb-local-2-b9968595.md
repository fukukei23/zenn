---
title: 【AWS SAM】sam local統合テストでDynamoDB Localと格闘した2つの障害と解決法
emoji: 🐛
type: tech
topics: ["AWS", "SAM", "Lambda", "DynamoDB", "統合テスト"]
published: false
---

## はじめに

AWS SAMを使って、LINEのwebhookで問い合わせを受付けてDynamoDBに保存し、日次バッチでまとめるミニCRMを構築していました。

単体テストは16件すべてグリーン。いざ `sam local start-api` を立ち上げて統合テスト…と思ったら、DynamoDB Local絡みで2つの障害に立て続けにハマり、完走までに丸1日を溶かしました。

この記事では、その2つの障害の症状・原因・解決法を順番に共有します。「ローカルで統合テストを回したいSAMユーザー」の参考になれば嬉しいです。

## 前提：ローカル統合テスト環境の構成

全体像は次のとおりです。

```
pytest（ホスト側）
  │ HTTPリクエスト
  ▼
sam local start-api（API Gatewayのエミュレータ）
  │
  ▼
Lambdaコード（Dockerコンテナ内で実行される）
  │ ← ここが問題！
  ▼
DynamoDB Local（ホスト側の8000番ポート）
```

DynamoDB Localは次のコマンドで起動し、テーブルは `--endpoint-url http://localhost:8000` を付けて事前に作成済みとします。

```bash
docker run -d -p 8000:8000 amazon/dynamodb-local
```

いちばん大事なポイントは、**テストコードはホストで動くのに、LambdaはDockerコンテナの中で動く**という点です。障害1はまさにここに起因します。

## 障害1：LambdaからDynamoDB Localに接続できない

### 症状

pytestからwebhookエンドポイントにPOSTすると502エラー。`sam local` のログには `Could not connect to the endpoint URL` が表示されました。

### 原因

最初、Lambdaコードのエンドポイントは `http://localhost:8000` と書いていました。

ところが `sam local` のLambdaはDockerコンテナ内で動きます。**コンテナから見た `localhost` は「コンテナ自身」** を指すため、ホスト側で起動中のDynamoDB Localには届かないのです。

### 解決法

エンドポイントを `host.docker.internal` に変更します。これはDocker Desktopが用意している「コンテナからホストを参照するための特殊なDNS名」です。

本番デプロイに影響しないよう、template.yamlの初期値は空にしておき、ローカル実行時だけ `--env-vars` で上書きする構成にしました。

```yaml:template.yaml（抜粋）
Resources:
  WebhookFunction:
    Type: AWS::Serverless::Function
    Properties:
      Environment:
        Variables:
          DYNAMODB_ENDPOINT: ""  # 本番では未指定
```

```json:env.local.json
{
  "WebhookFunction": {
    "DYNAMODB_ENDPOINT": "http://host.docker.internal:8000"
  }
}
```

```bash
sam local start-api --env-vars env.local.json
```

ここでの落とし穴は、**テストコード（ホスト側）は引き続き `http://localhost:8000` でOK** という非対称さです。「Lambda側だけホスト名が違う」ことを頭に入れておかないと、何度直しても動かない状態が続きます。

なおLinux環境では `host.docker.internal` がそのまま使えない場合があるため、DynamoDB Local起動時に `--add-host=host.docker.internal:host-gateway` を付ける対応が必要です。

## 障害2：「Unable to locate credentials」で認証エラー

### 症状

障害1を解消すると、今度は `botocore.exceptions.NoCredentialsError: Unable to locate credentials` が発生。ホスト側ではAWS認証情報を設定済みなのに、なぜ？と悩みました。

### 原因

boto3は `endpoint_url` にロ