"""phase0_layer1.py — 層1（suiko）定量評価の測定基盤（Phase 0・項目①）

層化抽出（Zenn20/外向き15/社内15=計50件）→前処理（frontmatter/コードブロック除外）→
suiko lint実行→カテゴリ別集計。抽出は決定論的等間隔（cherry-picking防止）。

使い方:
    python3 scripts/phase0/phase0_layer1.py extract   # サンプル抽出→JSON
    python3 scripts/phase0/phase0_layer1.py lint      # suiko実行→findings JSON
    python3 scripts/phase0/phase0_layer1.py report    # 集計レポート
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SUIKO = str(Path.home() / "bin" / "suiko")
OUT_DIR = Path.home() / ".claude" / "state" / "phase0-layer1"

SOURCES = {
    # クラス: (ディレクトリ, 抽出数, suiko --genre)
    "zenn": (Path.home() / "projects" / "zenn" / "articles", 20, "tech"),
    "gaimuki": (Path.home() / "projects" / "obsidian-ssot" / "40_CAREER" / "01_ドキュメント", 15, "business"),
    "shainai": (Path.home() / "projects" / "obsidian-ssot" / "01_DECISIONS", 15, "essay"),
}


def extract_samples(cls: str, source_dir: str, n: int) -> list[dict]:
    """ディレクトリ内の*.mdから決定論的等間隔でn件抽出する（cherry-picking防止）。"""
    files = sorted(str(p) for p in Path(source_dir).rglob("*.md"))
    if len(files) <= n:
        return [{"cls": cls, "path": p, "idx": i} for i, p in enumerate(files)]
    step = len(files) / n
    picked: list[dict] = []
    for i in range(n):
        picked.append({"cls": cls, "path": files[int(i * step)], "idx": int(i * step)})
    return picked


def preprocess_markdown(path: str) -> tuple[str, str]:
    """frontmatterのtitleと、コードブロック除去済み本文を返す。"""
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        body = text
        title = ""
    else:
        tm = re.search(r'^title:\s*"?(.*?)"?\s*$', m.group(1), re.MULTILINE)
        title = tm.group(1) if tm else ""
        body = text[m.end():]
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    return title, body


def run_suiko(path: str, genre: str) -> dict | None:
    """suiko lint --jsonを1ファイルに実行しfindingsを返す（失敗時None）。"""
    proc = subprocess.run(
        [SUIKO, "lint", "--json", "--genre", genre, "--reading-load", path],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode not in (0, 2):
        return None
    return json.loads(proc.stdout or "{}")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "extract":
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        all_samples: list[dict] = []
        for cls, (src, n, _g) in SOURCES.items():
            all_samples.extend(extract_samples(cls, str(src), n))
        (OUT_DIR / "samples.json").write_text(
            json.dumps(all_samples, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"extracted: {len(all_samples)} -> {OUT_DIR / 'samples.json'}")
        return 0
    if cmd == "lint":
        samples = json.loads((OUT_DIR / "samples.json").read_text(encoding="utf-8"))
        results: list[dict] = []
        for s in samples:
            genre = SOURCES[s["cls"]][2]
            tmp = OUT_DIR / "tmp_body.md"
            title, body = preprocess_markdown(s["path"])
            tmp.write_text(f"# {title}\n\n{body}" if title else body, encoding="utf-8")
            res = run_suiko(str(tmp), genre)
            results.append({**s, "ok": res is not None, "findings": res})
            mark = "ok" if res is not None else "FAIL"
            n_find = len(res.get("findings", [])) if res else 0
            print(f"[{mark}] {s['cls']} {Path(s['path']).name}: {n_find} findings")
        (OUT_DIR / "lint_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    if cmd == "report":
        results = json.loads((OUT_DIR / "lint_results.json").read_text(encoding="utf-8"))
        all_findings: list[dict] = []
        for r in results:
            if not r["ok"]:
                continue
            for f in r["findings"].get("findings", []):
                all_findings.append({**f, "cls": r["cls"], "src": r["path"], "lane": "lint"})
            for f in r["findings"].get("reading_load", {}).get("findings", []):
                all_findings.append({**f, "cls": r["cls"], "src": r["path"], "lane": "reading_load"})
        for cls in SOURCES:
            rows = [r for r in results if r["cls"] == cls]
            fails = [r for r in rows if not r["ok"]]
            n = len([f for f in all_findings if f["cls"] == cls])
            print(f"{cls}: {len(rows)}件 / 実行失敗{len(fails)} / findings {n}件")
        lines = ["# 層1（suiko）採点シート — Phase 0項目①（2026-09-24実測）", ""]
        lines.append("採点方法: 各指摘が「本当に問題か（正検知=1）/ 問題でない（誤検知=0）」をふくけい+CCが独立採点。")
        lines.append("")
        for i, f in enumerate(all_findings, 1):
            lines.append(
                f"| {i} | {f['cls']} | {Path(f['src']).name} | {f['lane']} | "
                f"{f['category']} | {f.get('severity', '')} | {f.get('excerpt', '')[:50]} | （　） |"
            )
        header = (
            "| # | cls | file | lane | category | sev | excerpt | 正検知? |\n"
            "|---|---|---|---|---|---|---|---|\n"
        )
        sheet = "\n".join(lines[:3]) + "\n" + header + "\n".join(lines[3:])
        (OUT_DIR / "scoring_sheet.md").write_text(sheet, encoding="utf-8")
        print(f"採点シート: {OUT_DIR / 'scoring_sheet.md'}（findings {len(all_findings)}件）")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
