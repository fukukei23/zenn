"""repost_weekly_summary.py の集計ロジック単体テスト（fixtureベース）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from repost_weekly_summary import aggregate, discord_line, render_markdown  # noqa: E402

FIXTURE = [
    # note: Caddy記事（10-25に13ビュー・10-24に10ビュー → 週間増分+3）
    {"date": "2026-10-24", "platform": "note", "note_id": "nA", "title": "Caddy記事", "views": 10, "likes": 1, "comments": None},
    {"date": "2026-10-25", "platform": "note", "note_id": "nA", "title": "Caddy記事", "views": 13, "likes": 2, "comments": None},
    # note: 別記事（増分0）
    {"date": "2026-10-24", "platform": "note", "note_id": "nB", "title": "停滞記事", "views": 100, "likes": None, "comments": None},
    {"date": "2026-10-25", "platform": "note", "note_id": "nB", "title": "停滞記事", "views": 100, "likes": None, "comments": None},
    # zenn: 転載元（10-25のみ1日分・前日無し → 増分は0として扱う）
    {"date": "2026-10-25", "platform": "zenn", "slug": "caddy-nginx-replacement-vps", "title": "Caddy記事", "views": 456},
    # 期間外（8日前）は集計対象外
    {"date": "2026-10-17", "platform": "note", "note_id": "nC", "title": "期間外", "views": 500, "likes": None, "comments": None},
]


def test_aggregate_counts_articles_and_views():
    s = aggregate(FIXTURE, week_end="2026-10-25", days=7)
    assert s["note_articles"] == 2
    assert s["zenn_articles"] == 1
    # 最新スナップショットの累積合計
    assert s["note_total_views"] == 13 + 100
    assert s["zenn_total_views"] == 456


def test_aggregate_weekly_gain_uses_day_diff():
    s = aggregate(FIXTURE, week_end="2026-10-25", days=7)
    # Caddy記事: 13-10=+3 / 停滞記事: 0 / zenn Caddy: 前日無し=0扱い
    assert s["note_weekly_gain"] == 3
    assert s["zenn_weekly_gain"] == 0


def test_aggregate_top_notes_sorted_by_gain():
    s = aggregate(FIXTURE, week_end="2026-10-25", days=7)
    # 増分のあるCaddy記事が1位
    assert s["top_notes"][0]["title"] == "Caddy記事"
    assert s["top_notes"][0]["weekly_gain"] == 3


def test_aggregate_null_likes_treated_as_zero():
    s = aggregate(FIXTURE, week_end="2026-10-25", days=7)
    # 停滞記事の likes=None は0扱いで集計が落ちない
    assert s["note_total_likes"] == 2


def test_render_markdown_contains_key_sections():
    s = aggregate(FIXTURE, week_end="2026-10-25", days=7)
    md = render_markdown(s)
    md_lower = md.lower()
    assert "note" in md_lower and "zenn" in md_lower
    assert "113" in md  # 累計が数値として出る（13+100）


def test_discord_line_is_single_line():
    s = aggregate(FIXTURE, week_end="2026-10-25", days=7)
    line = discord_line(s)
    assert "\n" not in line
    assert "note" in line.lower() and "zenn" in line.lower()
