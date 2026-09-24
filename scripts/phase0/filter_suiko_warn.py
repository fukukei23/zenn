#!/usr/bin/env python3
"""filter_suiko_warn.py — suiko lint --json 出力から暫定採用の2検出器のみ抽出する（Phase 0項目④）

v4準拠: redundant_light_verb / hype_expression の2カテゴリのみを
`カテゴリ: 抜粋` 形式で標準出力へ出す（info相当の参考提示・1行ずつ）。
壊れた入力・該当なしなら何も出さず exit 0（hookの非block設計に従う）。
"""
from __future__ import annotations

import json
import sys

ADMIT_CATEGORIES = ("redundant_light_verb", "hype_expression")


def filter_lines(payload: str) -> list[str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    findings = data.get("findings", []) if isinstance(data, dict) else data
    if not isinstance(findings, list):
        return []
    lines = []
    for x in findings:
        if isinstance(x, dict) and x.get("category") in ADMIT_CATEGORIES:
            excerpt = str(x.get("excerpt", ""))[:60]
            lines.append(f"{x.get('category')}: {excerpt}")
    return lines


def main() -> int:
    for line in filter_lines(sys.stdin.read()):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
