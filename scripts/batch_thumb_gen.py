"""drip用thumb.png一括生成（MiniMax経由・2026-10-21 L1164）。"""
import re
import sys
from pathlib import Path

QUEUE_PATH = Path(__file__).resolve().parent.parent / "repost-queue.md"
REPO_ROOT = QUEUE_PATH.parent
ARTICLES_DIR = REPO_ROOT / "articles"
MANUSCRIPTS_DIR = REPO_ROOT / "repost-manuscripts"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TITLE_RE = re.compile(r'^title:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)
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


def build_image_prompt(theme_en: str, keywords_en: str = "") -> str:
    """画像生成プロンプトを英字のみで構築する。

    日本語を prompt に含めると MiniMax が画像内に文字化けした日本語を描き込むため、
    呼び出し側は theme_en / keywords_en に英訳済み文字列を渡すこと（theme_map.yaml 参照）。
    """
    parts = [STYLE_PREFIX.rstrip(" --"), f"theme: {theme_en}"]
    if keywords_en:
        parts.append(f"elements: {keywords_en}")
    return ", ".join(parts)


def build_thumb_copy(title: str, limit: int = 15) -> str:
    """title を thumb 用コピー（10-15字）に整形する。

    1. 先頭の装飾記号（【】「」『』〈〉）を除去する
    2. 句読点・括弧があれば最初のものを境に切る
    3. どちらにも当てはまらなければ limit 字で切る
    """
    cleaned = title.strip().lstrip("【】「」『』〈〉〔〕")
    # 閉じ括弧は飾りの閉じとみなして、無条件に切り出す（例: 【NexusCore Stage 2】→ NexusCore Stage 2）
    for close in ("】", "」", "』", "〉", "〕"):
        idx = cleaned.find(close)
        if idx > 0:
            return cleaned[:idx]
    for sep in ("、", "。", "（", "(", "：", ":"):
        idx = cleaned.find(sep)
        if 0 < idx <= limit:
            return cleaned[:idx]
    return cleaned[:limit]


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


def main(verbose: bool = True) -> int:
    """queue [ ] 全件を process_slug で順次処理し結果を集約する。

    戻り値: 0=全件 ok / skipped・1=1 件以上失敗（failed/no-article/image-failed/thumb-failed/exception）

    注意: image 実生成は MCP 経由のため CC が手動で行う前提（plan Task 5/6）。
    本 main はテスト用のバッチ動作確認・バッチスクリプト雛形用。
    """
    slugs = parse_pending_slugs(str(QUEUE_PATH))
    if not slugs:
        if verbose:
            print("[batch] queue empty")
        return 0
    if verbose:
        print(f"[batch] processing {len(slugs)} slugs: {slugs}")
    results: dict[str, str] = {}
    for i, slug in enumerate(slugs, 1):
        if verbose:
            print(f"[batch] ({i}/{len(slugs)}) {slug}")
        try:
            results[slug] = process_slug(slug)
        except Exception as e:  # noqa: BLE001
            print(f"[batch] exception: {slug}: {e}")
            results[slug] = "exception"
    summary: dict[str, int] = {}
    for v in results.values():
        summary[v] = summary.get(v, 0) + 1
    if verbose:
        print(f"[batch] SUMMARY: {summary}")
    failed = [k for k, v in results.items() if v not in ("ok", "skipped")]
    if failed:
        if verbose:
            print(f"[batch] FAILED: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for s in parse_pending_slugs(str(QUEUE_PATH)):
            print(s)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "main-dry":
        sys.exit(main(verbose=True))
    sys.exit(0)
