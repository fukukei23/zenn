---
title: "【NexusCore事例】Celeryタスクの冪等設計：Redis分散ロックで重複実行を防ぐ"
emoji: "🛡️"
type: "tech"
topics: ["python", "celery", "redis", "backend"]
published: false
---

## はじめに

バックグラウンド処理にPythonのCeleryを採用しているシステムにおいて、最も頭を悩ませる問題の一つが「タスクの重複実行」です。

Docker ComposeやKubernetesなどのコンテナ環境でCeleryワーカーを動かす場合、OOM（メモリ不足）による強制終了や、ノードのスケールインなどによりワーカーが突然停止することがあります。Celeryのデフォルトの挙动では、タスクの実行中にワーカーがダウンすると、メッセージブローカーはタスクを「未完了」とみなし、別のワーカーに再配信します（At-least-once配信）。

これにより、Slackへの通知が複数回来てしまったり、DBのデータが重複して作成されてしまうといった副作用が発生します。本記事では、自身の開発しているバックエンドシステム「NexusCore」の事例をもとに、Celeryタスクの冪等性（何度実行しても同じ結果になること）を保証するための具体的な実装方針を解説します。

## 1. Celeryの基本設定とリトライ戦略

まず大前提として、タスクロストを防ぐための基本設定を行います。`acks_late`（タスク完了後にACKを返す）と`track_started`（タスク開始状態をトラッキングする）を有効にします。

加えて、意図しない重複実行を防ぐために「決定論的タスクID」を採用します。通常、CeleryはランダムなUUIDをタスクIDとして割り当てますが、ユーザーによる連続クリックなどで全く同じタスクがエンキューされてしまうのを防ぐため、条件から一意のIDを生成して指定します。

```python
from celery import Celery

app = Celery("nexuscore", broker="redis://redis:6379/0")

# 基本設定
app.conf.update(
    task_acks_late=True,
    task_track_started=True,
    task_reject_on_worker_lost=True, # ワーカーロスト時に再配信させる
)

@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True, # 指数バックオフでリトライ
    max_retries=3,
)
def process_data(self, payload: dict):
    # 決定論的タスクIDの生成（Enqueue時に指定して渡す）
    # e.g. task_id = hashlib.sha256(f"{payload['project_id']}".encode()).hexdigest()
    pass
```

さらにProducer（タスクをキューに入れる側）でも、指定した`task_id`が既にキューに存在しないかチェックするガードを実装し、二重エンキューを事前に弾くようにしました。

## 2. Redis分散ロック（SETNX）によるタスク先頭ガード

Celeryのリトライ機能やワーカーの再起動により、どうしても同じタスクIDのタスクが並行で実行されてしまうレースコンディションが発生し得ます。これを防ぐため、タスク処理の先頭に**Redis分散ロック**を導入します。

Redisの`SET NX`（存在しない場合のみセットする）コマンドを利用し、最初にロックを獲得したタスクのみが処理を続行できるようにします。

```python
import redis
from contextlib import contextmanager

redis_client = redis.StrictRedis.from_url("redis://redis:6379/1")

@contextmanager
def task_lock(lock_id: str, timeout: int = 300):
    """
    Redis SETNXを利用した分散ロック
    """
    status = redis_client.set(lock_id, "locked", nx=True, ex=timeout)
    if status:
        try:
            yield True
        finally:
            redis_client.delete(lock_id)
    else:
        # 既にロックが存在する場合は重複実行とみなしてスキップ
        yield False

# Celeryタスク内での利用
@app.task
def send_report_task(user_id: str):
    lock_key = f"lock:send_report:{user_id}"
    
    with task_lock(lock_key) as acquired:
        if not acquired:
            print("Task is already running. Skipping...")
            return
            
        # ここに実際の処理を書く
        send_email_to_user(user_id)
```

このような`task_lock.py`ユーティリティを作成し、全タスクのエントリーポイントで実行するようにしました。これにより、万が一同じタスクが同時に起動してしまっても、後から起動した方は即座にスキップされます。また、処理が成功したことを示すフラグを別途Redisに保存しておき、成功済みのタスクがリトライされた場合にもスキップする仕組み（SUCCESS skip）を組み込んでいます。

## 3. NotificationLogによる副作用の完全防止

Redisロックは非常に強力ですが、アプリケーションレベルでの制御であるため、ネットワークの瞬断などでロック取得とDBコミットのタイミングがズレる可能性を完全には排除できません。

そこで、特にSlack通知など外部への副作用を伴う処理においては、DBのUNIQUE制約を利用した最終的な防波堤を構築します。

専用の`NotificationLog`モデルを作成し、送信前に「対象となる一意のキー（タスクIDなど）」をUNIQUE制約付きでINSERTしようとします。既にレコードが存在して一意制約違反のエラーが出た場合は、送信済みとみなして処理をスキップします。

```python
from django.db import models, IntegrityError

class NotificationLog(models.Model):
    task_id = models.CharField(max_length=255, unique=True)
    target_id = models.CharField(max_length=255)
    channel = models.CharField(max_length=50)
    
def send_slack_notification(task_id: str, message: str):
    try:
        # UNIQUE制約で重複送信を防止
        NotificationLog.objects.create(task_id=task_id, ...)
        # DB保存が成功したらSlack APIを叩く
        call_slack_api(message)
    except IntegrityError:
        # 既にtask_idが存在するため、送信済みとしてスキップ
        pass
```

DBのトランザクションとUNIQUE制約を利用することで、多段なリトライや分散ロックをすり抜けたとしても、絶対にSlackに重複メッセージが飛んでいくことを防ぐことができます。

## おわりに

今回の改修で、「Celeryワーカー環境の不安定さ」を前提とした堅牢なタスク処理を実現できました。

1. **Producer / Broker側**: 決定論的task_idと二重エンキュー拒否
2. **タスク先頭**: Redis SETNXによる分散ロックと成功済みスキップ
3. **外部副作用**: DB UNIQUE制約によるNotificationLog

非同期処理において「ブローカーは必ず一度以上配信してくる（At-least-once）」という前提で設計することは、バックエンドエンジニアにとって非常に重要です。アプリケーション起点のロック（Redis）とデータ起点の制約（DB）を組み合わせた多層防御を取り入れることで、夜間にシステムが暴走してSlackが通知で埋め尽くされるような事故を未然に防ぐことができます。

本記事が、皆さんのCelery運用設計の一助になれば幸いです。