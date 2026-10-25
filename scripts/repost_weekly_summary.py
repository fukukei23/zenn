#!/usr/bin/env python3
"""転載ドリップ週次サマリ: metrics.jsonl を集計して週次報告を生成する。

使い方: python3 repost_weekly_summary.py [metrics.jsonl]
出力: stdout にmarkdown・--discord で1行形式を出力
集計: 直近7日（--days で変更可）の日次差分（増分）と最新累積値
spec: docs/superpowers/specs/2026-10-25-転載ドリップ効果測定ループ-design.md
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

METRICS_DEFAULT = Path.home() / "projects" / "zenn" / "repost-metrics" / "metrics.jsonl"


def load_metrics(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _key(r: dict) -> str:
    return r.get("note_id") or r.get("slug") or ""


def aggregate(rows: list[dict], week_end: str, days: int = 7) -> dict:
    """直近days分のmetrics行から週次サマリを集計する（純関数・テスト対象）。"""
    end = date.fromisoformat(week_end)
    start = end - timedelta(days=days - 1)
    recent = [
        r
        for r in rows
        if r.get("date") and start <= date.fromisoformat(r["date"]) <= end
    ]

    def latest_by_article(platform: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in recent:
            if r.get("platform") != platform:
                continue
            k = _key(r)
            if k not in out or r["date"] > out[k]["date"]:
                out[k] = r
        return out

    def weekly_gain(platform: str, articles: dict[str, dict]) -> int:
        gain = 0
        for k, latest in articles.items():
            prev_by_date = {
                r["date"]: r for r in recent
                if r.get("platform") == platform and _key(r) == k
            }
            earlier = [d for d in prev_by_date if d < latest["date"]]
            if not earlier:
                continue  # 前日分が無い記事の増分は0扱い（取得開始直後の過大計上防止）
            prev = prev_by_date[max(earlier)]
            v_now = latest.get("views") or 0
            v_prev = prev.get("views") or 0
            gain += max(v_now - v_prev, 0)
        return gain

    notes = latest_by_article("note")
    zenns = latest_by_article("zenn")

    def top_list(articles: dict[str, dict], platform: str, n: int = 5) -> list[dict]:
        items = []
        for k, latest in articles.items():
            prev_by_date = {
                r["date"]: r for r in recent
                if r.get("platform") == platform and _key(r) == k
            }
            earlier = [d for d in prev_by_date if d < latest["date"]]
            if earlier:
                prev = prev_by_date[max(earlier)]
                gain = max((latest.get("views") or 0) - (prev.get("views") or 0), 0)
            else:
                gain = 0
            items.append({
                "title": latest.get("title", k),
                "weekly_gain": gain,
                "views": latest.get("views") or 0,
                "likes": latest.get("likes") or 0,
            })
        return sorted(items, key=lambda x: -x["weekly_gain"])[:n]

    return {
        "period": f"{start.isoformat()}〜{end.isoformat()}",
        "note_articles": len(notes),
        "zenn_articles": len(zenns),
        "note_total_views": sum(r.get("views") or 0 for r in notes.values()),
        "zenn_total_views": sum(r.get("views") or 0 for r in zenns.values()),
        "note_total_likes": sum(r.get("likes") or 0 for r in notes.values()),
        "note_weekly_gain": weekly_gain("note", notes),
        "zenn_weekly_gain": weekly_gain("zenn", zenns),
        "top_notes": top_list(notes, "note"),
        "top_zenn": top_list(zenns, "zenn"),
    }


def render_markdown(s: dict) -> str:
    lines = [
        f"## 転載ドリップ週次サマリ（{s['period']}）",
        "",
        f"- note: {s['note_articles']}記事・累計ビュー {s['note_total_views']:,}・週間増分 +{s['note_weekly_gain']:,}・スキ {s['note_total_likes']:,}",
        f"- Zenn: {s['zenn_articles']}記事・累計ビュー {s['zenn_total_views']:,}・週間増分 +{s['zenn_weekly_gain']:,}",
        "",
        "### note 上位（週間増分）",
    ]
    for t in s["top_notes"]:
        lines.append(f"- {t['title'][:40]} — 週間+{t['weekly_gain']:,}（累計 {t['views']:,}・スキ {t['likes']:,}）")
    lines.append("")
    lines.append("### Zenn 上位（週間増分）")
    for t in s["top_zenn"]:
        lines.append(f"- {t['title'][:40]} — 週間+{t['weekly_gain']:,}（累計 {t['views']:,}）")
    return "\n".join(lines)


def discord_line(s: dict) -> str:
    return (
        f"転載ドリップ週次（{s['period']}）: note {s['note_articles']}記事 累計{s['note_total_views']:,}ビュー（週間+{s['note_weekly_gain']:,}・スキ{s['note_total_likes']}）"
        f" / Zenn {s['zenn_articles']}記事 累計{s['zenn_total_views']:,}ビュー（週間+{s['zenn_weekly_gain']:,}）"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("metrics", nargs="?", default=str(METRICS_DEFAULT))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--discord", action="store_true")
    args = ap.parse_args()
    rows = load_metrics(Path(args.metrics))
    if not rows:
        print("metrics.jsonl が空です（収集が1回も成功していない）", file=sys.stderr)
        return 1
    today = datetime.now().date().isoformat()
    s = aggregate(rows, week_end=today, days=args.days)
    if args.discord:
        print(discord_line(s))
    else:
        print(render_markdown(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
