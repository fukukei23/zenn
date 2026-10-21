import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import batch_thumb_gen as bg


def _fake_jpg(path: str) -> str:
    """最小限の 1x1 JPEG を書き出す（テスト用 fake image）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb0043000302020303020303030304030304050805"
            "0504040405050a06060a09090a09090909090909090909090909090909090909090909090909090909"
            "0909ffd9"))
    return path


def test_process_slug_skips_when_thumb_png_exists(tmp_path, monkeypatch):
    slug = "skip-me"
    art = tmp_path / "articles" / f"{slug}.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text('---\ntitle: "skip"\n---\n\nbody\n', encoding="utf-8")
    repo = tmp_path
    mdir = repo / "repost-manuscripts" / slug
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "thumb.png").write_bytes(b"already")
    called = []
    monkeypatch.setattr(bg, "_image_to_path", lambda *a, **k: called.append(a) or _fake_jpg(a[1]))
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "ARTICLES_DIR", repo / "articles")
    monkeypatch.setattr(bg, "MANUSCRIPTS_DIR", repo / "repost-manuscripts")
    monkeypatch.setattr(bg, "QUEUE_PATH", repo / "queue.md")
    result = bg.process_slug(slug)
    assert result == "skipped"
    assert called == []


def test_process_slug_succeeds_on_happy_path(tmp_path, monkeypatch):
    slug = "happy"
    art = tmp_path / "articles" / f"{slug}.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text('---\ntitle: "Happy"\n---\n\nbody body body\n' * 10, encoding="utf-8")
    repo = tmp_path
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "ARTICLES_DIR", repo / "articles")
    monkeypatch.setattr(bg, "MANUSCRIPTS_DIR", repo / "repost-manuscripts")
    monkeypatch.setattr(bg, "QUEUE_PATH", repo / "queue.md")

    def fake_img(prompt, out):
        return _fake_jpg(out)

    monkeypatch.setattr(bg, "_image_to_path", fake_img)

    def fake_compose(slug_, repo_root):
        thumb = repo_root / "repost-manuscripts" / slug_ / "thumb.png"
        thumb.write_bytes(b"thumb-bytes")

    monkeypatch.setattr(bg, "_compose_thumb", fake_compose)
    result = bg.process_slug(slug)
    assert result == "ok"
    assert (repo / "repost-manuscripts" / slug / "thumb.png").exists()


def test_process_slug_returns_no_article_when_missing(tmp_path, monkeypatch):
    repo = tmp_path
    art_dir = repo / "articles"
    art_dir.mkdir()
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "ARTICLES_DIR", art_dir)
    monkeypatch.setattr(bg, "MANUSCRIPTS_DIR", repo / "repost-manuscripts")
    monkeypatch.setattr(bg, "QUEUE_PATH", repo / "queue.md")
    assert bg.process_slug("nope-slug") == "no-article"


def test_process_slug_returns_image_failed_when_no_bg(tmp_path, monkeypatch):
    slug = "no-bg"
    art = tmp_path / "articles" / f"{slug}.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text('---\ntitle: "x"\n---\n\nbody\n', encoding="utf-8")
    repo = tmp_path
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "ARTICLES_DIR", repo / "articles")
    monkeypatch.setattr(bg, "MANUSCRIPTS_DIR", repo / "repost-manuscripts")
    monkeypatch.setattr(bg, "QUEUE_PATH", repo / "queue.md")
    monkeypatch.setattr(bg, "_image_to_path", lambda p, o: "")  # 空パス返す
    monkeypatch.setattr(bg, "_compose_thumb", lambda s, r: None)
    assert bg.process_slug(slug) == "image-failed"


def test_process_slug_returns_thumb_failed_when_no_thumb(tmp_path, monkeypatch):
    slug = "no-thumb"
    art = tmp_path / "articles" / f"{slug}.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text('---\ntitle: "x"\n---\n\nbody\n', encoding="utf-8")
    repo = tmp_path
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "ARTICLES_DIR", repo / "articles")
    monkeypatch.setattr(bg, "MANUSCRIPTS_DIR", repo / "repost-manuscripts")
    monkeypatch.setattr(bg, "QUEUE_PATH", repo / "queue.md")

    def fake_img(prompt, out):
        _fake_jpg(out)
        return out

    monkeypatch.setattr(bg, "_image_to_path", fake_img)
    # _compose_thumb は no-op（thumb.png 書かれない）
    monkeypatch.setattr(bg, "_compose_thumb", lambda s, r: None)
    assert bg.process_slug(slug) == "thumb-failed"
