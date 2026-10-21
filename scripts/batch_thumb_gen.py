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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for s in parse_pending_slugs(str(QUEUE_PATH)):
            print(s)
        sys.exit(0)
    sys.exit(0)
