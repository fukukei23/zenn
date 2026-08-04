#!/usr/bin/env python3
"""全 articles/*.md をZenn規約でバリデーション（CI用・違反時exit 1）。

generator.validate_article を全記事に適用。手動編集由来の違反も捕捉し、
Zennデプロイのブロッカー増加を未然に防ぐ最終防波堤（B′案ステップ7）。
"""

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import validate_article

ARTICLE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "articles"
)


def validate_all(article_dir=ARTICLE_DIR):
    """全記事をスキャンし違反リスト [(filename, [errors])] を返す（空=全合格）。"""
    if not os.path.isdir(article_dir):
        return []
    files = sorted(f for f in os.listdir(article_dir) if f.endswith(".md"))
    all_slugs = [os.path.splitext(f)[0] for f in files]
    dup_slugs = {s for s, c in Counter(all_slugs).items() if c > 1}

    violations = []
    for f in files:
        with open(os.path.join(article_dir, f), encoding="utf-8") as fh:
            content = fh.read()
        m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not m:
            violations.append((f, ["frontmatterなし"]))
            continue
        fm = m.group(1)
        tm = re.search(r'^title:\s*"?(.*?)"?\s*$', fm, re.MULTILINE)
        title = tm.group(1) if tm else ""
        slug = os.path.splitext(f)[0]
        existing = [s for s in all_slugs if s != slug]
        errs = validate_article(title, slug, existing)
        if slug in dup_slugs:
            errs.append(f"slug重複: '{slug}' が複数ファイルで重複")
        if errs:
            violations.append((f, errs))
    return violations


def main():
    violations = validate_all()
    if not violations:
        print("✅ All articles valid")
        return 0
    print(f"❌ {len(violations)}件の違反記事:")
    for f, errs in violations:
        print(f"  {f}:")
        for e in errs:
            print(f"    - {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
