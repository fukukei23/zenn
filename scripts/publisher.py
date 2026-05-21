#!/usr/bin/env python3
"""Publish approved article: change published flag and push."""

import json
import os
import re
import subprocess
import sys


def get_issue_body(token, repo_full, issue_number):
    import requests

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    resp = requests.get(
        f"https://api.github.com/repos/{repo_full}/issues/{issue_number}",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("body", "")


def extract_slug(issue_body):
    match = re.search(r"<!-- slug: (.+?) -->", issue_body)
    if match:
        return match.group(1).strip()

    match = re.search(r"\*\*slug\*\*: `(.+?)`", issue_body)
    if match:
        return match.group(1).strip()

    return None


def set_published_true(article_path):
    with open(article_path, encoding="utf-8") as f:
        content = f.read()

    if "published: false" in content:
        content = content.replace("published: false", "published: true", 1)
    elif "published: true" in content:
        print("Already published: true")
        return False
    else:
        print("No published field found in frontmatter")
        return False

    with open(article_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def git_commit_push(slug):
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "add", f"articles/{slug}.md"], check=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], capture_output=True
    )
    if result.returncode == 0:
        print("No changes to commit")
        return

    subprocess.run(
        ["git", "commit", "-m", f"publish: {slug}"], check=True
    )
    subprocess.run(["git", "push"], check=True)
    print(f"Pushed: articles/{slug}.md (published: true)")


def set_github_output(name, value):
    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"{name}={value}\n")


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    repo_full = os.environ.get("GITHUB_REPOSITORY", "fukukei23/zenn")

    if not issue_number:
        print("ISSUE_NUMBER not set")
        sys.exit(1)

    print(f"Processing issue #{issue_number}...")
    issue_body = get_issue_body(token, repo_full, int(issue_number))
    slug = extract_slug(issue_body)
    if not slug:
        print("Could not extract slug from issue body")
        sys.exit(1)

    print(f"Article slug: {slug}")
    article_path = f"articles/{slug}.md"

    if not os.path.exists(article_path):
        print(f"Article file not found: {article_path}")
        sys.exit(1)

    changed = set_published_true(article_path)
    if changed:
        git_commit_push(slug)

    set_github_output("slug", slug)
    set_github_output("published", "true")
    print(f"Done: {slug} published")


if __name__ == "__main__":
    main()
