#!/usr/bin/env python3
"""Scan GitHub repos for recent activity to find article topics."""

import json
import os
import sys
from datetime import datetime, timedelta

import requests

OWNER = "fukukei23"

# メタ系リポジトリ（コンテンツ/知識ベース管理は記事ネタ不適・再帰になるため除外）
EXCLUDE_REPOS = {"zenn", "obsidian-ssot"}


def github_get(url, token, params=None):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def discover_active_repos(token, owner, since_iso):
    """認証ユーザーの直近活動リポジトリをpushed_at順で抽出。

    /user/repos?sort=pushed から最新100件取得 → pushed_at >= since で
    フィルタ → owner絞り込み → 除外リスト適用。リポジトリ名のリストを返す。
    """
    data = github_get(
        "https://api.github.com/user/repos",
        token,
        params={"sort": "pushed", "direction": "desc", "per_page": 100},
    )
    repos = []
    for r in data if isinstance(data, list) else []:
        name = r.get("name", "")
        repo_owner = (r.get("owner") or {}).get("login", "")
        pushed = r.get("pushed_at", "")
        if repo_owner != owner:
            continue
        if name in EXCLUDE_REPOS:
            continue
        if pushed and pushed >= since_iso:
            repos.append(name)
    return repos


def scan_repo(token, owner, repo, since):
    commits_data = github_get(
        f"https://api.github.com/repos/{owner}/{repo}/commits",
        token,
        params={"since": since, "per_page": 30},
    )
    commits = [
        {
            "message": c["commit"]["message"].split("\n")[0][:120],
            "date": c["commit"]["author"]["date"],
        }
        for c in (commits_data if isinstance(commits_data, list) else [])[:20]
    ]

    prs_data = github_get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        token,
        params={
            "state": "closed",
            "sort": "updated",
            "direction": "desc",
            "per_page": 10,
        },
    )
    prs = [
        {
            "title": p["title"],
            "body": (p.get("body") or "")[:500],
        }
        for p in (prs_data if isinstance(prs_data, list) else [])[:5]
    ]

    try:
        readme = github_get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            token,
            params={"Accept": "application/vnd.github.v3.raw"},
        )
        readme_text = readme if isinstance(readme, str) else str(readme)
    except Exception:
        readme_text = ""

    return {
        "repo": repo,
        "commits": commits,
        "prs": prs,
        "readme": readme_text[:1000],
    }


def main():
    token = os.environ.get("PERSONAL_ACCESS_TOKEN", "")
    if not token:
        print("ERROR: PERSONAL_ACCESS_TOKEN not set")
        sys.exit(1)

    since = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
    repos = discover_active_repos(token, OWNER, since)

    if not repos:
        print("No recently active repos, skipping")
        with open(os.path.join(os.path.dirname(__file__), "..", "skip.flag"), "w") as f:
            f.write("no_activity")
        return

    print(f"Scanning {len(repos)} repos since {since[:10]}: {', '.join(repos)}")

    results = []
    for repo in repos:
        try:
            result = scan_repo(token, OWNER, repo, since)
            n_commits = len(result["commits"])
            n_prs = len(result["prs"])
            print(f"  {repo}: {n_commits} commits, {n_prs} PRs")
            results.append(result)
        except Exception as e:
            print(f"  {repo}: ERROR - {e}")

    output_path = os.path.join(os.path.dirname(__file__), "..", "scan_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {len(results)} repos scanned → scan_results.json")

    if not any(r["commits"] or r["prs"] for r in results):
        print("WARNING: No recent activity found in any repo")
        with open(os.path.join(os.path.dirname(__file), "..", "skip.flag"), "w") as f:
            f.write("no_activity")


if __name__ == "__main__":
    main()
