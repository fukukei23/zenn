import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import batch_thumb_gen as bg


def test_parse_queue_returns_pending_slugs(tmp_path):
    q = tmp_path / "queue.md"
    q.write_text(
        "- [x] done-slug-1 — done\n"
        "- [ ] pending-slug-a — a\n"
        "- [n] half-slug-b — b\n"
        "- [ ] pending-slug-c — c\n",
        encoding="utf-8",
    )
    assert bg.parse_pending_slugs(str(q)) == ["pending-slug-a", "pending-slug-c"]


def test_parse_real_queue_has_18_slugs():
    slugs = bg.parse_pending_slugs(str(bg.QUEUE_PATH))
    assert len(slugs) == 18
    assert slugs[0] == "nexuscore-stage-2-architect-debugger-guardian-3"
    assert all(isinstance(s, str) and len(s) > 0 for s in slugs)
