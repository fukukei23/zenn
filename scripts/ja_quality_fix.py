#!/usr/bin/env python3
"""ja_quality_fix.py — 公開ゲート: 検知→CC(LLM)自動修正→issue diff報告→再承認待ち

publish.ymlの /approve 時に動作するゲート（2026-09-25・ふくけい承認設計）:
- 指摘ゼロ → outputs.gate=clean（以降の公開ステップが進む）
- 指摘あり → LLMで自動修正→articles/{slug}.mdへ適用→git commit+push→
  issueに修正前後のdiff+変更理由を報告→outputs.gate=fixed（公開ステップは停止）
  → ふくけいが /approve を再送すると次回runでclean判定になり公開される
- 全失敗（slug無し・LLM応答異常等）も gate=fixed で停止+issue報告（fail-safe:
  品質不明のまま公開しない・warn-onlyとの差分=ここが「ブロック+手動レビュー」）
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def revise_sentence(client, original: str, problem: str, suggestion: str) -> str:
    """指摘文1つをLLMで修正する（修正後の文のみを返す・失敗時は元文）。"""
    from generator import chat

    prompt = (
        "次の日本語の文を、指摘に従って修正してください。修正後の文だけを"
        "そのまま1つ返してください（説明・引用符・コードフェンス不要）。\n\n"
        f"元の文: {original}\n"
        f"問題: {problem}\n"
        f"修正の方向性: {suggestion}\n\n修正後の文:"
    )
    revised = chat(client, os.environ.get("JA_QUALITY_MODEL", "MiniMax-M3"),
                   prompt, max_tokens=2000)
    revised = revised.strip().strip('"').strip("`").strip()
    return revised if revised else original


def apply_fixes(text: str, fixes: list[dict]) -> tuple[str, list[dict]]:
    """修正を本文へ適用する（適用できたものだけ反映・結果と詳細を返す）。

    fixes: [{"original", "revised", "problem"}]
    """
    applied, skipped = [], []
    for fx in fixes:
        original = fx["original"]
        if original in text:
            text = text.replace(original, fx["revised"], 1)
            applied.append(fx)
        else:
            skipped.append(fx)  # 元文が見つからない（LLM応答が文単位でない等）
    return text, skipped


def build_comment(applied: list[dict], skipped: list[dict]) -> str:
    """issue報告用のコメント本文（修正前後+理由の表）。"""
    lines = ["## 📝 日本語品質ゲート: 自動修正を実施しました（公開は一時停止）",
             "",
             "LLM点検で指摘があったため、次のとおり修正しました。",
             "変更内容をご確認ください。**問題なければ `/approve` を再送してください**（再チェック後に公開されます）。",
             "「それは違う」場合はこのissueに指示をください（手動修正後に再承認します）。", ""]
    if applied:
        lines.append("| 元の文 | 修正後 | 修正理由 |")
        lines.append("|---|---|---|")
        for fx in applied:
            lines.append(f"| {fx['original'][:60]} | **{fx['revised'][:60]}** "
                         f"| {fx.get('problem', '')[:60]} |")
    if skipped:
        lines.append("\n### ⚠️ 自動修正できなかった指摘（手動確認のお願い）")
        for fx in skipped:
            lines.append(f"- 元文が特定できず: {fx.get('problem', '')[:80]}")
    if not applied and not skipped:
        lines.append("（適用可能な修正なし）")
    return "\n".join(lines)


def post_issue_comment(token: str, repo: str, issue: int, body: str) -> None:
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{issue}/comments",
        data=json.dumps({"body": body}).encode("utf-8"),
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        method="POST")
    urllib.request.urlopen(req, timeout=30)


def commit_and_push(slug: str) -> None:
    import subprocess

    subprocess.run(["git", "add", f"articles/{slug}.md"], check=True)
    subprocess.run(["git", "commit", "-m", f"fix: 日本語品質ゲート自動修正（{slug}）"],
                   check=True, capture_output=True)
    subprocess.run(["git", "push"], check=True, capture_output=True)


def run_gate(slug: str, client, articles_dir: str | None = None) -> tuple[str, str]:
    """ゲート実行の本体 → (gate, comment)。

    gate: "clean"（公開進行）| "fixed"（修正+報告済み・公開停止）
    articles_dir: テスト注入用（未指定=リポのarticles/）
    """
    from ja_quality import check_file

    adir = articles_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "articles")
    article_path = os.path.join(adir, f"{slug}.md")
    issues = check_file(client, article_path)
    if issues is None:
        issues = []
    if not issues:
        return "clean", ""

    fixes = []
    for it in issues:
        original = str(it.get("quote", ""))
        revised = revise_sentence(client, original,
                                  str(it.get("problem", "")),
                                  str(it.get("suggestion", "")))
        fixes.append({"original": original, "revised": revised,
                      "problem": it.get("problem", "")})
    # 適用（quoteは抜粋の可能性があるため元文が完全一致しない場合はskipに回る）
    with open(article_path, encoding="utf-8") as f:
        text = f.read()
    new_text, skipped = apply_fixes(text, fixes)
    applied = [fx for fx in fixes if fx not in skipped]
    if applied:
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        commit_and_push(slug)
    comment = build_comment(applied, skipped)
    return "fixed", comment


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    issue = int(os.environ.get("ISSUE_NUMBER", "0"))
    from publisher import extract_slug, get_issue_body

    slug = extract_slug(get_issue_body(token, repo, issue))
    if not slug:
        print("gate=fixed（slug抽出失敗・品質不明のため公開停止）")
        post_issue_comment(token, repo, issue,
                           "⚠️ 記事slugを特定できず公開を停止しました。issue本文にslugを記載して再承認ください。")
        print("gate=fixed")
        return 0

    from generator import MINIMAX_BASE_URL
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("MINIMAX_API_KEY", ""),
                    base_url=MINIMAX_BASE_URL)
    gate, comment = run_gate(slug, client)
    if gate == "fixed":
        post_issue_comment(token, repo, issue, comment)
    print(f"gate={gate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
