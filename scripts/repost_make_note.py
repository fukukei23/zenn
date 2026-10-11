#!/usr/bin/env python3
"""Zenn記事md → note転載用mdへの自動変換（第1批次の手動変換を機械化）。

変換内容（note エディタの制約対応・2026-10-11実測ベース）:
  - frontmatter除去・タイトル抽出
  - 冒頭にZenn出典行
  - 表（| ... |）→ 箇条書き（セルは「 ― 」連結・2列目相当を太字化はせず素直に連結）
  - mermaidブロックはコードブロックのまま（noteはコードブロック表示可・図にはならない旨の注記付き）
使い方: python3 repost_make_note.py <articles/slug.md> <出力先note.md>
"""
import re
import sys
from pathlib import Path


def convert_table_block(lines: list[str]) -> list[str]:
    """表行ブロックを箇条書きへ変換（区切り行|---|は除外）。"""
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # 区切り行
        rows.append(cells)
    out = []
    for cells in rows:
        cells = [c.replace("**", "") for c in cells]
        out.append(f"- {' ― '.join(cells)}")
    return out


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")
    fm = text.split("---")
    front, body = fm[1], "---".join(fm[2:]).strip()
    m = re.search(r'^title:\s*"(.*)"', front, re.M)
    title = m.group(1) if m else src.stem
    slug = src.stem

    lines = body.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.extend(convert_table_block(block))
            continue
        out.append(lines[i])
        i += 1

    header = f"※本記事は [Zenn](https://zenn.dev/fukukei23/articles/{slug}) でも公開しています。\n\n# {title}\n\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(header + "\n".join(out).strip() + "\n", encoding="utf-8")
    n_tables = sum(1 for ln in out if ln.startswith("- ") and " ― " in ln)
    print(f"[make-note] {slug}: 変換完了（{len(dst.read_text(encoding='utf-8'))}文字・表行→箇条書き{n_tables}行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
