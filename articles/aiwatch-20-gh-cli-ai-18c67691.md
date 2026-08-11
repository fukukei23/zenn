---
title: "【AIWatch実装】週$20コストキャップの設計：gh CLIでAIリポジトリ利用料を自動監視"
emoji: "💰"
type: "tech"
topics: ["Python", "AI", "コスト管理", "gh CLI"]
published: false
---

# はじめに

AIコーディングアシスタント（Claude Codeなど）を自律的に動かしたり、GitHubのトレンドをAIに監視させたりするシステムを構築し始めると、必ず直面する壁があります。それが**「コストの暴発」**です。

AIが意図せぬ無限ループに陥ったり、サードパーティのAPI制限に引っかかってエラー解決を繰り返したりすると、あっという間にAPIの利用料が青天井になってしまいます。

今回は、AIを用いたリポジトリ監視パイプライン（AIWatch）を構築する中で、**「週あたり$20の利用料で必ずストップさせる」**というコスト管理機構を実装しました。本記事では、`cost.json`によるコストの永続化、しきい値超過時の自動停止、そして`gh CLI`の認証チェックを組み合わせた、実践的なコストキャップの設計について解説します。

# 1. コストキャップの設計：`cost.json`による状態の永続化

AIの利用料を制限する上で最も重要なのは、「今週いくら使ったか」という**状態を永続化（保存）すること**です。

メモリ上でコストを管理しているだけでは、スクリプトがクラッシュした時や、PCを再起動した時に累積コストがリセットされてしまい、せっかくのキャップが形骸化してしまいます。

そこで、シンプルかつ確実な方法としてJSONファイル（`cost.json`）を利用します。このファイルには以下の情報を記録します。

- 週の開始日（`week_start`）
- 現在の累積コスト（`total_cost`）

スクリプトの起動時にこのファイルを読み込み、AIを動かす前に「累積コスト ＋ 予想される今回のコスト」が上限（$20）を超えないかをチェックします。超える場合は処理をスキップし、安全に停止させます。

# 2. 安全な運用のためのガードレール（gh CLI認証チェック）

コスト管理と同じくらい重要なのが、**「無駄なAPIコールを防ぐこと」**です。

今回はGitHubの公開リポジトリ情報を取得するために`gh CLI`（GitHub Command Line Interface）を利用しています。AIにリポジトリのスター数や成長率を分析させるためです。
しかし、`gh CLI`の認証トークンが期限切れになっていたり、未ログインの状態でスクリプトを動かしてしまうと、APIは401エラーを返し続けます。

最悪なのは、このエラーメッセージをそのままAI（LLM）に投げてしまうケースです。AIは「エラーを解決しよう」として無駄な推論トークンを消費し、結果として**何も成果を出さないままコストだけが吸い取られていきます。**

これを防ぐために、メインのパイプラインを動かす前に`gh auth status`コマンドをバックグラウンドで実行し、認証が有効かどうかをチェックする事前ガードレールを設けました。認証が切れていれば、AIを起動する前に即座にスクリプトを終了させます。

# 3. Pythonでの実装例：週次リセットとコストチェック

それでは、実際のPythonコードを見てみましょう。
以下は、`cost.json`を読み書きし、週次でコストをリセットしつつ、$20のキャップを超えないかを判定するクラスの実装例です。

```python
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

COST_LIMIT = 20.0
COST_FILE = Path("/path/to/cost.json")

class CostManager:
    def __init__(self):
        self.data = self._load_cost_data()

    def _load_cost_data(self):
        """コストデータをファイルから読み込む（不存在なら初期化）"""
        if COST_FILE.exists():
            with open(COST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 初期データの作成
        return {
            "week_start": datetime.now().strftime("%Y-%m-%d"),
            "total_cost": 0.0
        }

    def _save_cost_data(self):
        """コストデータをファイルへ保存"""
        with open(COST_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2)

    def _reset_if_new_week(self):
        """週が変わっていればコストをリセットする"""
        week_start_date = datetime.strptime(self.data["week_start"], "%Y-%m-%d")
        
        # 週の開始日から7日以上経過していたらリセット
        if datetime.now() - week_start_date >= timedelta(days=7):
            self.data["week_start"] = datetime.now().strftime("%Y-%m-%d")
            self.data["total_cost"] = 0.0
            self._save_cost_data()

    def can_process(self, estimated_cost: float) -> bool:
        """今回の処理コストを加算しても上限を超えないか判定"""
        self._reset_if_new_week()

        if self.data["total_cost"] + estimated_cost >= COST_LIMIT:
            print(f"[STOP] 週次コスト上限に到達しました: ${self.data['total_cost']:.2f} / ${COST_LIMIT:.2f}")
            return False

        return True

    def update_cost(self, actual_cost: float):
        """実際にかかったコストを累積に加算して保存"""
        self.data["total_cost"] += actual_cost
        self._save_cost_data()

def check_gh_auth() -> bool:
    """gh CLIの認証状態をチェックする"""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], 
            capture_output=True, 
            text=True
        )
        # gh CLIは認証成功時にも終了コード0を返さないことがあるため、
        # 出力メッセージから判定するか、終了コードをチェックします
        if result.returncode == 0:
            return True
        
        print("[ERROR] gh CLIの認証が切れています。ログインしてください。")
        return False
    except Exception as e:
        print(f"[ERROR] gh CLIの検証に失敗しました: {e}")
        return False

# メインの実行フロー
if __name__ == "__main__":
    if not check_gh_auth():
        exit(1) # 認証エラーなら即終了

    manager = CostManager()
    estimated_api_cost = 0.5 # 今回の処理でかかる想定コスト

    if manager.can_process(estimated_api_cost):
        print("処理を開始します...")
        # --- ここにAIを使った処理が入る ---
        # ...
        # 処理が終わったら実際のコストを記録
        manager.update_cost(estimated_api_cost)
        print(f"処理完了。現在の累積コスト: ${manager.data['total_cost']:.2f}")
    else:
        print("今週のコストキャップに達したため、処理をスキップします。")
```

この実装のポイントは、**「推定コスト（estimated_cost）で事前チェックを行い、処理後に実際のコスト（actual_cost）を記録する」**という二段構えの防御です。これにより、予想以上にトークンを消費した場合でも、次回の実行時に確実にストップがかかります。

# おわりに

AIを用いた開発や自動化パイプラインを運用する上で、「コスト管理」はもはやエンタープライズ向けの要件だけではありません。個人開発であっても、意図しない課金を防ぐための必須のガードレールとなります。

今回実装した `$20の週次キャップ` と `gh CLIの認証チェック` の組み合わせは、非常にシンプルながらも強力な防御線となります。
「AIは信用するが、全権限を任せきりにしない」というバランスを取ることで、安心して自動化システムを運用できるようになります。皆さんのAI運用においても、ぜひコスト管理の仕組みを早い段階で組み込んでみてください。