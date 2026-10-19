---
title: "Claude Code LLMプロキシ運用の1週間：中国語混入からsystemd化までの4教訓"
emoji: "🔧"
type: "tech"
topics: ["ClaudeCode", "LLM運用", "systemd", "MiniMax"]
published: false
---

## はじめに

Claude Code を複数のLLMで使い分けるため、ローカルにLLMプロキシを立てて運用している。設定やスクリプトは自分のリポジトリでバージョン管理しているのだが、ある1週間で「新モデルの品質問題」と「プロセス管理の事故」が連続して発生し、20件近いコミットで収束させた。

この記事ではその騒動を時系列で振り返り、安定運用のために必要だった**4つの教訓**を初心者向けにまとめる。systemd unitの最小例と、Pythonのテストコード例も併記する。

## 教訓1: プレビューモデルを常用経路に混ぜない

発端は、コードレビュー用AIの日本語出力に突然**中国語が混ざり始めた**ことだった。

原因を追うと、新しく導入した MiniMax M3.1-Flash-Preview。プレビュー版は応答が速い反面、出力品質の保証がなく、日本語と中国語はトークンが近いためか、応答の一部が中国語に置き換わっていた。

応急対応として、複数LLMでコードレビューする multi-llm-review のモデル優先順位を安定版のM3へ戻した。

ここで学んだのは「**モデル指定は1か所にまとめる**」こと。優先順位だけ戻しても、MCPサーバーの設定やプロキシのフォールバック先にプレビュー版が残っており、掃討に追加のコミットが2つ必要になった。モデル名の定義が分散していると、ロールバック漏れは必ず起きる。

## 教訓2: プロセス管理はsystemdに任せる

中国語混入の調査中に、もっと深刻な問題が見つかった。プロキシを起動スクリプトの手動バックグラウンド実行で運用していたため、**管理外の野良インスタンス**が重複起動し、「今どのプロセスが・どのモデルで応答しているのか」が分からなくなっていたのだ。

そこで起動スクリプトをsystemdのラッパーとして登録し直した。systemdとはLinux標準のサービス管理機構で、unitという設定ファイルに従ってプロセスの起動・監視・再起動を引き受けてくれる。最小構成はこれだけだ。

```ini
[Unit]
Description=LLM proxy for Claude Code
After=network-online.target

[Service]
ExecStart=/path/to/start-glm-proxy.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

ユーザー権限で動かすunitとして保存したら、以下で有効化する。

```bash
systemctl --user daemon-reload
systemctl --user enable --now llm-proxy.service
```

これで (1) クラッシュ時の自動再起動、(2) `systemctl status` での状態確認、(3) 二重起動の防止、が一挙に実現できた。

## 教訓3: 「誰が応答したか」をテストで固定する

systemd化しても、「ヘルスチェックが通っている」ことと「意図したモデルが応答している」ことは別だ。野良インスタンスや退避したはずの旧モデルが応答していても、ヘルスチェックは正常を返してしまう。

そこでヘルスチェック（`proxy_health_ok`）に**応答者識別**のテストを追加した。Python（pytest）ではこう書ける。

```python
import json
import urllib.request

ENDPOINT = "http://127.0.0.1:8000"  # ローカルプロキシの例

def get_responder_model() -> str:
    """実際に応答したモデルIDを取得する"""
    with urllib.request.urlopen(f"{ENDPOINT}/v1/models", timeout=10) as res:
        payload = json.load(res)
    return payload["data"][0]["id"]