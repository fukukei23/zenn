---

title: "【Claude Code】cron多重発火を防ぐstamp+年齢方式の排他設計：同一commit重複を構造的封じ"
emoji: "🔒"
type: "tech"
topics: ["ClaudeCode", "Python", "cron", "自動化", "テスト"]
published: false
---

# はじめに

Claude Code の durable cron(常駐型の定期実行)を設定管理用の自前リポジトリで運用し始めて数ヶ月、ある朝ログを見ると**まったく同じ commit に対して整合性チェックが2回連続で発火していました**。1回で済むはずの処理が重複し、レポートが二重に飛び、トークンも無駄に消化されていた——というのが今回の事故です。

この記事では、多重発火がなぜ起きたのかを整理したうえで、**「stamp+年齢」方式の時間ベース排他ロック**でこれを構造的に封じる Python 実装を、テスト4件付きで紹介します。

# 1. なぜ durable cron は多重発火するのか

durable cron は「実行予定を永続化し、プロセスが落ちても再開する」仕組みです。この頑健さが裏目に出ることがあります。

- セッション再起動や復旧のタイミングで、**前回と同じ対象(同一 commit)にジョブが再発火される**
- 発火側は「まだ実行していない」と認識しているため、通常の終了コードでは防げない

定番の flock(ファイルロック)は「**同時に走るプロセス同士**の排他」には有効です。しかしプロセスが正常終了した時点でロックも消えるため、「**終わったあとの再発火**」は原理的に防げません。つまり必要なのは、プロセスの生存ではなく「直近に実行済みか」の記録でした。

# 2. stamp+年齢方式の設計

方針は3点だけです。

1. ジョブ開始時に **stamp ファイル**(開始時刻を記録)を書く
2. 次の発火では stamp の**年齢**(現在時刻 − 記録時刻)を見て、しきい値未満なら「実行中/直近実行済み」とみなしスキップ
3. 年齢がしきい値超過なら**残骸(スタロック)とみなして実行を許可** — 削除忘れで永久に止まる事故を防ぐ

しきい値は「ジョブの最長実行時間 + 余裕」に設定します。手元では30分にしました。最悪しきい値ぶんの重複は1回だけ許す代わりに、永続ブロックが起こらないトレードオフです。

さらに、**ロックを弾いた事実を `flock_busy` として JSON Lines に追記**します。多重発火が「起きていたこと」自体を事後検知できるのがポイントで、修正後の運用はこのログを1行見るだけで済んでいます。なお flock(プロセス排他)と本方式(時間排他)は役割が違うため併用で、自分の環境ではチェック系ジョブに stamp+年齢、使用量集計に flock ラッパーを当て、durable cron 残り6件すべてを排他化しました。

# 3. Python 実装とテスト4件

```python
# cron_lock.py — stamp+年齢方式の排他ロック
import json
import time
from dataclasses import dataclass
from pathlib import Path

STATE_DIR = Path("/path/to/state/cron")    # stamp と busy ログの置き場所
BUSY_LOG = STATE_DIR / "flock_busy.jsonl"  # ロック拒否の履歴(JSON Lines)

@dataclass
class LockResult:
    acquired: bool
    reason: str

def _read_stamp(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def _log_busy(job: str, age: float, prev: float | None) -> None:
    """ロックを弾いた事実を jsonl に1行追記(多重発火の事後検知用)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), "job": job, "event": "flock_busy",
              "lock_age_seconds": round(age, 1), "previous_started_at": prev}
    with BUSY_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def try_acquire(job: str, max_age_seconds: float) -> LockResult:
    stamp_path = STATE_DIR / f"{job}.stamp.json"
    now = time.time()
    stamp = _read_stamp(stamp_path)

    if stamp:
        age = now - float(stamp.get("started_at", 0))
        if age < max_age_seconds:
            _log_busy(job, age, stamp.get("started_at"))
            return LockResult(False, f"locked: age={age:.0f}s")

    # tmp → rename のアトミック更新で、同時書き込みでも壊れない
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = stamp_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"job": job, "started_at": now}), encoding="utf-8")
    tmp.replace(stamp_path)
    return LockResult(True, "acquired")
```

cron 側の呼び出しは2行です。多重発火は「異常」ではなく「正常系として弾く」扱いにします。

```python
if not try_acquire("ssot-check", max_age_seconds=1800).acquired:
    raise SystemExit(0)  # 静かに終了
# ... 本処理 ...
```

テストは4件。特に3つ目が重要で、これがないと「多重発火防止を入れたら今度は止まったまま」になります。

```python
# test_cron_lock.py
import json, time
import cron_lock

def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(cron_lock, "STATE_DIR", tmp_path)
    monkeypatch.setattr(cron_lock, "BUSY_LOG", tmp_path / "flock_busy.jsonl")

def _write_stamp(tmp_path, job, started_at):
    (tmp_path / f"{job}.stamp.json").write_text(
        json.dumps({"job": job, "started_at": started_at}), encoding="utf-8")

def test_first_run_acquires(tmp_path, monkeypatch):  # 1. 初回は取得できる
    _setup(tmp_path, monkeypatch)
    assert cron_lock.try_acquire("ssot-check", 1800).acquired is True

def test_recent_stamp_blocks_and_logs(tmp_path, monkeypatch):  # 2. 若いstampは弾く
    _setup(tmp_path, monkeypatch)
    _write_stamp(tmp_path, "ssot-check", time.time() - 30)
    assert cron_lock.try_acquire("ssot-check", 1800).acquired is False
    line = (tmp_path / "flock_busy.jsonl").read_text().splitlines()[0]
    assert json.loads(line)["event"] == "flock_busy"

def test_stale_stamp_is_reclaimed(tmp_path, monkeypatch):  # 3. 残骸は回収できる
    _setup(tmp_path, monkeypatch)
    _write_stamp(tmp_path, "ssot-check", time.time() - 7200)
    assert cron_lock.try_acquire("ssot-check", 1800).acquired is True

def test_busy_log_schema(tmp_path, monkeypatch):  # 4. 弾いた記録のスキーマ検証
    _setup(tmp_path, monkeypatch)
    _write_stamp(tmp_path, "usage-sync", time.time() - 10)
    cron_lock.try_acquire("usage-sync", 1800)
    rec = json.loads((tmp_path / "flock_busy.jsonl").read_text().splitlines()[0])
    assert {"ts", "job", "event", "lock_age_seconds"} <= set(rec)
```

# おわりに

「同じ commit が連続発火する」という事故は、flock のようなプロセス単位の排他では防げず、**実行履歴を時間で判定するレイヤー**を足す必要がありました。stamp+年齢方式は依存もファイル1つだけで、数十行で導入できます。

導入後、`flock_busy` の jsonl を見ると修正前には気づけなかった再発火が数件記録されており、「止める」だけでなく「見える化」の効果も実感しました。durable cron を運用している方は、一度自分のジョブの多重発火を疑ってみることをおすすめします。