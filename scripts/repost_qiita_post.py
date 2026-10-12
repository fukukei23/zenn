#!/usr/bin/env python3
"""Qiita転載投稿スクリプト（API v2・トークンは環境変数$QIITA_ACCESS_TOKENで受ける）。

使い方:
  python3 repost_qiita_post.py post <qiita.mdのパス> <tagsカンマ区切り>   # 限定公開で投稿
  python3 repost_qiita_post.py publish <item_id>                          # 公開へ切替
トークン値をstdoutへ出力しない（セキュリティルール）。
"""
import json
import os
import sys
import urllib.request

API = "https://qiita.com/api/v2"


def log(msg: str) -> None:
    print(f"[qiita-post] {msg}", flush=True)


def request(path: str, method: str, payload: dict | None = None) -> tuple[int, dict | list]:
    token = os.environ.get("QIITA_ACCESS_TOKEN", "")
    if not token:
        log("環境変数QIITA_ACCESS_TOKENが空（exit 3）")
        sys.exit(3)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            body = json.loads(res.read().decode())
            return res.status, body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode() or "{}")
        print(f"[qiita-post] HTTPエラー {e.code}: {body.get('message', '')} {body.get('detail', '')}", flush=True)
        return e.code, body


def main() -> int:
    mode = sys.argv[1]
    if mode == "post":
        md_path = sys.argv[2]
        tags = [{"name": t.strip()} for t in sys.argv[3].split(",") if t.strip()]
        # タイトルは第4引数で明示渡し（本文からの抽出はコードコメント誤検出事故2回の実績あり）
        title = sys.argv[4] if len(sys.argv) > 4 else ""
        text = open(md_path, encoding="utf-8").read()
        body = text.strip()
        if title:
            body = body.replace(f"# {title}\n", "", 1).strip()
        status, res = request("/items", "POST", {
            "title": title, "body": body, "tags": tags,
            "private": True, "tweet": False,
        })
        log(f"post: HTTP={status} / item_id={res.get('id')} / url={res.get('url')}")
        return 0 if status in (200, 201) else 1
    if mode == "publish":
        item_id = sys.argv[2]
        # PATCHは部分更新不可（400）のため現状取得→完全ペイロードで更新（2026-10-12実測）
        status, item = request(f"/items/{item_id}", "GET")
        if status != 200:
            log(f"現状取得失敗: HTTP={status}")
            return 1
        payload = {
            "title": item["title"], "body": item["body"],
            "tags": [{"name": t["name"]} for t in item["tags"]], "private": False,
        }
        status, res = request(f"/items/{item_id}", "PATCH", payload)
        log(f"publish: HTTP={status} / url={res.get('url')} / private={res.get('private')}")
        return 0 if status in (200, 201) else 1
    log(f"不明モード: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
