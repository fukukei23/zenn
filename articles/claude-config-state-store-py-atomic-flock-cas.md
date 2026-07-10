---
title: "state_store.pyで学ぶプロセス間同期：atomic+flock+CASで安全な状態管理"
emoji: "🔒"
type: "tech"
topics: ["python", "プロセス管理", "設計思想"]
published: false
---

## はじめに

バックグラウンドで動く自動化タスクを複数実行していると、「今どのタスクが動いているのか？」「予期せず停止したタスクの状態をどうリセットするのか？」といった**プロセス間での状態管理**に悩まされることがあります。

複数のプロセスから同じ設定ファイルや状態ファイル（JSONなど）を同時に読み書きしようとすると、データ競合が起きてファイルが破損したり、古い状態を元に誤った処理を続けてしまったりする問題が発生します。

今回は、自身の自動化リポジトリでバックグラウンドタスクのPID管理と古い状態（Stale）の検出を実装するために新設した `state_store.py` の設計思想を解説します。具体的な実装である「アトミック操作」「flock」「CAS（Compare-And-Swap）」という3つのキーワードを通じて、実践的なプロセス間同期のパターンを学んでいきましょう。

## 1. データ競合を防ぐ仕組み：アトミック操作と flock

複数のプロセスが同時に同じファイルにアクセスすると何が起きるでしょうか。
例えば、プロセスAとプロセスBが同時に同じJSONファイルを開き、それぞれ別のデータを書き込んだ場合、最後に保存したプロセスのデータだけが残り、もう一方の更新は消滅してしまいます。

これを防ぐための基本的なアプローチが**ファイルロック（flock）**による排他制御です。

Pythonの標準ライブラリである `fcntl` モジュールを使うことで、ファイル単位のロックを実現できます。`flock` を使ってファイルをロックしている間は、他のプロセスはそのファイルへのアクセスを待機させられるため、安全に読み書きが可能です。

さらに、データの書き込みにおいては**アトミック操作（不可分操作）**を心がける必要があります。アトミックなファイル更新の一般的なパターンは、「一時ファイルに書き込んだ後、リネームして本番ファイルを上書きする」という手法です。

```python
import fcntl
import os
import json
from pathlib import Path

STATE_FILE = Path("/path/to/state.json")

def update_state_safely(new_data: dict):
    """flockとアトミックなリネームを使って安全に状態を更新する"""
    # ファイルを開いてロックを取得（他のプロセスは待機される）
    with open(STATE_FILE, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        
        # ロック取得後に処理を実行
        f.seek(0)
        try:
            current_state = json.load(f)
        except json.JSONDecodeError:
            current_state = {}
            
        current_state.update(new_data)
        
        # 一時ファイルに新しい状態を書き込む
        tmp_file = STATE_FILE.with_suffix('.tmp')
        with open(tmp_file, 'w') as tmp:
            json.dump(current_state, tmp, indent=2)
            
        # 一時ファイルを本番ファイルにアトミックにリネーム（保存）
        os.replace(tmp_file, STATE_FILE)
        
        # ロックを解放（コンテキストマネージャーの終了時にも自動解放される）
        fcntl.flock(f, fcntl.LOCK_UN)
```

このように、ロックの取得とアトミックなリネームを組み合わせることで、書き込み中のクラッシュによるファイル破損を強力に防ぐことができます。

## 2. プロセスのPID管理と「Stale（古い）」状態の検出

バックグラウンドタスクを管理する際、「今どのタスクが動いているか」を記録するためによく使われるのが **PID（プロセスID）** です。
状態ファイル（`state.json`）に現在動いているタスクのPIDを保存しておき、後からそのPIDが存在するかを確認することで、タスクが生存しているかをチェックします。

しかし、単なるPIDのチェックには致命的な落とし穴があります。それは**「PIDの再利用」**です。

OSはプロセスが終了した後、時間が経つと同じPIDを新しいプロセスに割り当てることがあります。たとえば、あなたが管理しているタスクAがPID `1234` だったとします。タスクAが異常終了した後、全く別の新しいプログラム（例えばブラウザのプロセスなど）が同じPID `1234` を割り当てられたとします。
この状態でPIDだけをチェックすると、「プロセスが存在するからタスクAはまだ動いている」と誤判定してしまいます。

この問題を解決するために、PIDに加えて **プロセスの生成時刻（`create_time`）** を一緒に保存する仕組みを導入しました。

```python
import psutil

def is_process_stale(pid: int, expected_create_time: float) -> bool:
    """保存されたPIDと生成時刻を照合し、古い状態かどうかを判定する"""
    if not psutil.pid_exists(pid):
        return True  # プロセス自体が存在しない＝古い状態
    
    try:
        p = psutil.Process(pid)
        # 保存していた生成時刻と現在のプロセスの生成時刻が一致するか確認
        if p.create_time() != expected_create_time:
            return True  # 時刻が一致しない＝PIDが別プロセスに再利用された（古い状態）
            
        return False  # プロセスは生きている
    except psutil.NoSuchProcess:
        return True
```

`psutil` ライブラリを使うことで、PIDだけでなくプロセスの生成時刻を正確に取得できます。この2つの情報を照合することで、PIDの再利用による誤判定を防ぎ、確実に「Stale（古くなってしまった不要な状態）」を検出できるようになります。

## 3. CAS（Compare-And-Swap）による安全な状態遷移

複数プロセスが並行して動く環境において、状態を安全に更新するための有名なアルゴリズムに **CAS（Compare-And-Swap）** があります。

CASは非常にシンプルな仕組みです。
1. 現在の状態（値）を読み込む
2. 新しい状態を計算する
3. 実際に書き込む直前に、「自分が読み込んだ後から他のプロセスによって状態が変更されていないか」を確認する
4. 変更されていなければ、新しい状態をアトミックに書き込む。変更されていたら最初からやり直す（リトライする）

これをPythonと `flock` を組み合わせて実装すると、より堅牢な状態管理ストア（`state_store`）が完成します。

```python
def set_running_state(task_id: str, max_retries: int = 3):
    """CASパターンを用いて安全に状態を'running'にする"""
    for attempt in range(max_retries):
        with open(STATE_FILE, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            
            # 1. 現在の状態を読み込む
            f.seek(0)
            try:
                current_state = json.load(f)
            except json.JSONDecodeError:
                current_state = {}
            
            # 2. 現在の状態をチェック（他のプロセスが書き換えていないか）
            if current_state.get("status") == "running":
                # すでに他のタスクが動いている場合
                # ※実際には、ここで前述の is_process_stale を使って
                #   動いているプロセスが古いものかどうかを判定します
                raise RuntimeError("別のタスクがすでに実行中です")
            
            # 3. 新しい状態を準備する
            current_pid = os.getpid()
            new_state = {
                "status": "running",
                "task_id": task_id,
                "pid": current_pid,
                "create_time": psutil.Process(current_pid).create_time()
            }
            
            # 4. アトミックに書き込みを実行（ロックされているため安全）
            tmp_file = STATE_FILE.with_suffix('.tmp')
            with open(tmp_file, 'w') as tmp:
                json.dump(new_state, tmp, indent=2)
            os.replace(tmp_file, STATE_FILE)
            
            return True  # 成功
            
    raise RuntimeError("状態の更新に失敗しました（リトライ回数超過）")
```

このように、「確認してから書き込む」処理をロックの内側で行うことで、`state_store` は常に一貫性を保ちつつ、複数プロセスからのバッティングを防ぐことができます。

## おわりに

バックグラウンドタスクの自動化やループ処理が複雑化してくると、シェルスクリプトや複数のPythonスクリプトが並行して動くようになります。そのような環境において「状態を安全に保存・参照すること」は、システム全体の安定性に直結します。

今回は `state_store.py` の実装を通じて、以下の重要なパターンを紹介しました。

- **flock とアトミックなリネーム**によるファイル破損の防止
- **PID と `create_time` の照合**による確実なStale検出
- **CAS（Compare-And-Swap）パターン**による安全な状態遷移

これらのプロセス間同期の仕組みを一度導入しておけば、予期せぬ競合バグに悩まされることは激減します。自動化ツールやバックグラウンドプロセスを自作している方は、ぜひこの設計パターンを取り入れてみてください。