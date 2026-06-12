#!/usr/bin/env python3
"""Generate Zenn article drafts using 2-stage LLM pipeline (GLM + MiniMax)."""

import json
import os
import re
import sys
from datetime import datetime

from openai import OpenAI

GLM_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
MINIMAX_BASE_URL = "https://api.minimax.io/v1"
TOPIC_MODEL = "MiniMax-M2.7"
ARTICLE_MODEL = "GLM-5.1"
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_topic_history():
    return load_json(os.path.join(SCRIPTS_DIR, "topic_history.json"))


def save_topic_history(history):
    save_json(history, os.path.join(SCRIPTS_DIR, "topic_history.json"))


def chat(client, model, prompt, max_tokens=4000):
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def extract_topics(minimax_client, scan_results, past_titles):
    scan_summary = json.dumps(scan_results, ensure_ascii=False, indent=2)
    if len(scan_summary) > 8000:
        scan_summary = scan_summary[:8000] + "\n... (truncated)"

    past_list = "\n".join(f"  - {t}" for t in past_titles) if past_titles else "  (なし)"

    prompt = f"""以下のGitHub活動ログから、Zenn技術記事のネタを3つ提案してください。

過去に書いたトピック（重複禁止）:
{past_list}

活動ログ:
{scan_summary}

条件:
- 公務員からIT転職を目指す人の実務経験に基づく内容
- 初心者にもわかる説明
- 具体的なコード例を含められる題材
- 1記事で完結するスコープ

出力形式（JSON配列のみ、説明文は不要）:
[{{"title": "記事タイトル", "summary": "2-3行の概要", "repo": "リポジトリ名", "tags": ["tag1", "tag2"]}}]"""

    text = chat(minimax_client, TOPIC_MODEL, prompt, max_tokens=1000)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return []


def generate_article(glm_client, topic, scan_results):
    repo_data = next(
        (r for r in scan_results if r["repo"] == topic.get("repo")),
        scan_results[0] if scan_results else {},
    )
    context = json.dumps(repo_data, ensure_ascii=False, indent=2)[:3000]

    prompt = f"""以下の情報をもとに、Zenn技術記事を書いてください。

タイトル案: {topic['title']}
概要: {topic['summary']}
対象リポジトリ: {topic.get('repo', '')}
タグ: {', '.join(topic.get('tags', ['ai']))}

参考情報（リポジトリの最近の活動）:
{context}

要件:
- Zenn Markdown形式
- frontmatter（title, emoji, type, topics, published: false）を必ず含める
- 記事全体をコードフェンス（```markdown```）で囲まないこと。生のMarkdownとして出力すること
- 構成: はじめに → 本文（2-4セクション） → おわりに
- PythonまたはTypeScriptのコード例を最低1つ含める
- 日本語で書く
- 初心者向けのわかりやすい説明
- 2000-3000文字程度
- 実務経験に基づく具体的な内容（抽象論だけにしない）"""

    return chat(glm_client, ARTICLE_MODEL, prompt, max_tokens=8000)


def slug_from_title(title):
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    if ascii_part and len(ascii_part) > 5:
        return ascii_part[:60]
    return f"auto-{datetime.now().strftime('%Y%m%d-%H%M')}"


def strip_code_fence(text):
    """LLMが出力を```markdown ... ```で囲んだ場合に外す。"""
    text = text.strip()
    # ```markdown\n...\n``` or ```\n...\n``` パターン
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def ensure_frontmatter(article, title, tags):
    article = strip_code_fence(article)
    if article.strip().startswith("---"):
        return article

    tags_str = json.dumps(tags if tags else ["ai", "automation"], ensure_ascii=False)
    fm = f"""---
title: "{title}"
emoji: "📝"
type: "tech"
topics: {tags_str}
published: false
---

"""
    return fm + article


def main():
    glm_client = OpenAI(
        api_key=os.environ["GLM_API_KEY"],
        base_url=GLM_BASE_URL,
    )
    minimax_client = OpenAI(
        api_key=os.environ["MINIMAX_API_KEY"],
        base_url=MINIMAX_BASE_URL,
    )

    scan_path = os.path.join(SCRIPTS_DIR, "..", "scan_results.json")
    skip_flag = os.path.join(SCRIPTS_DIR, "..", "skip.flag")
    if os.path.exists(skip_flag):
        print("Skipping: no activity found by scanner")
        sys.exit(0)

    scan_results = load_json(scan_path)
    if not scan_results:
        print("No scan results found")
        sys.exit(1)

    history = load_topic_history()
    past_titles = [t["title"] for t in history.get("topics", [])]

    print("Stage 1: Extracting topics (MiniMax)...")
    topics = extract_topics(minimax_client, scan_results, past_titles)
    if not topics:
        print("No topics found. Exiting.")
        sys.exit(0)

    for i, t in enumerate(topics):
        print(f"  [{i+1}] {t['title']} ({t.get('repo', '?')})")

    topic = topics[0]
    print(f"\nStage 2: Generating article (GLM) → {topic['title']}")
    article = generate_article(glm_client, topic, scan_results)

    tags = topic.get("tags", ["ai", "automation"])
    article = ensure_frontmatter(article, topic["title"], tags)

    slug = slug_from_title(topic["title"])
    article_dir = os.path.join(SCRIPTS_DIR, "..", "articles")
    os.makedirs(article_dir, exist_ok=True)
    article_path = os.path.join(article_dir, f"{slug}.md")

    with open(article_path, "w", encoding="utf-8") as f:
        f.write(article)

    meta = {
        "slug": slug,
        "title": topic["title"],
        "repo": topic.get("repo", ""),
        "summary": topic.get("summary", ""),
        "tags": tags,
    }
    meta_path = os.path.join(SCRIPTS_DIR, "..", "article_meta.json")
    save_json(meta, meta_path)

    history.setdefault("topics", []).append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "title": topic["title"],
        "slug": slug,
        "source_repo": topic.get("repo", ""),
    })
    save_topic_history(history)

    print(f"\nArticle saved: articles/{slug}.md")


if __name__ == "__main__":
    main()
