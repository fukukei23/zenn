"""drip用thumb.png一括生成（MiniMax経由・2026-10-21 L1164）。"""
import re
import sys
from pathlib import Path

QUEUE_PATH = Path(__file__).resolve().parent.parent / "repost-queue.md"
REPO_ROOT = QUEUE_PATH.parent
ARTICLES_DIR = REPO_ROOT / "articles"
MANUSCRIPTS_DIR = REPO_ROOT / "repost-manuscripts"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TITLE_RE = re.compile(r'^title:\s*"(.*?)"\s*$', re.MULTILINE)
PENDING_RE = re.compile(r"^- \[ \] (\S+)")

STYLE_PREFIX = (
    "minimal flat illustration, vibrant accent color, modern Japanese tech blog cover, "
    "no text, no people faces, abstract iconography, soft shadows -- "
)


def parse_pending_slugs(queue_path: str) -> list[str]:
    """queue [ ] 行から slug を順序保持で抽出。"""
    out: list[str] = []
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            m = PENDING_RE.match(line)
            if m:
                out.append(m.group(1))
    return out


def load_article_title_and_head(article_path: str, head_chars: int = 200) -> tuple[str, str]:
    """記事の frontmatter title と本文先頭 head_chars 字を返す。"""
    text = Path(article_path).read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    title = ""
    if m:
        tm = TITLE_RE.search(m.group(1))
        if tm:
            title = tm.group(1).strip()
        body = text[m.end():].strip()
    else:
        body = text.strip()
    body_one_line = re.sub(r"\s+", " ", body)
    return title, body_one_line[:head_chars]


def build_image_prompt(title: str, head: str) -> str:
    """スタイル prefix + title + 概要を結合して画像生成プロンプト作成。"""
    return f"{STYLE_PREFIX}title={title} | abstract={head}"


def build_thumb_copy(title: str, limit: int = 15) -> str:
    """title を thumb 用コピー（10-15字）に整形。句読点があれば最初の句読点で切る。"""
    for sep in ("、", "。", "（", "("):
        idx = title.find(sep)
        if 0 < idx <= limit:
            return title[:idx]
    return title[:limit]


def process_slug(slug: str) -> str:
    """1 slug 分の画像生成+thumb合成。既存 thumb.png があれば skipped。"""
    out_dir = MANUSCRIPTS_DIR / slug
    thumb = out_dir / "thumb.png"
    if thumb.exists():
        return "skipped"
    art = ARTICLES_DIR / f"{slug}.md"
    if not art.exists():
        print(f"[batch] article missing: {slug}")
        return "no-article"
    title, head = load_article_title_and_head(str(art))
    prompt = build_image_prompt(title, head)
    out_dir.mkdir(parents=True, exist_ok=True)
    bg_path = out_dir / "bg.jpg"
    _image_to_path(prompt, str(bg_path))
    if not bg_path.exists() or bg_path.stat().st_size == 0:
        print(f"[batch] image gen failed: {slug}")
        return "image-failed"
    _compose_thumb(slug, REPO_ROOT)
    if not thumb.exists():
        print(f"[batch] thumb compose failed: {slug}")
        return "thumb-failed"
    print(f"[batch] OK: {slug}")
    return "ok"


def _image_to_path(prompt: str, out_jpg: str) -> str:
    """MCP mcp__minimax-official__text_to_image 経由で画像を out_jpg に保存する。

    本関数はプレースホルダ実装（CC がツールブロックで直接 MCP 呼び出し後に
    out_jpg へ画像を書き込む運用が正・plan Task 5/6 参照）。process_slug の
    バインディングポイントとして残し、テスト時は monkeypatch でスタブする。

    引数 prompt: 画像生成プロンプト（process_slug で build_image_prompt から渡される）
    引数 out_jpg: 保存先パス（process_slug で mkdir 済み）
    戻り値: 呼び出し側で存在確認される out_jpg パス"""
    return out_jpg


def _compose_thumb(slug: str, repo_root: Path) -> None:
    """既存 repost_make_thumb.py を subprocess で呼ぶ。"""
    import subprocess
    bg_path = repo_root / "repost-manuscripts" / slug / "bg.jpg"
    thumb = repo_root / "repost-manuscripts" / slug / "thumb.png"
    title, _ = load_article_title_and_head(str(repo_root / "articles" / f"{slug}.md"))
    copy = build_thumb_copy(title)
    subprocess.run([
        "python3",
        str(repo_root / "scripts" / "repost_make_thumb.py"),
        str(bg_path), str(thumb), "AI", copy,
    ], check=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for s in parse_pending_slugs(str(QUEUE_PATH)):
            print(s)
        sys.exit(0)
    sys.exit(0)
