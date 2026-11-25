# drip 用 thumb.png 一括生成スクリプト 実装計画（L1164）

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans（inline実行・今セッション単一・commitごと承認確認）

**Goal:** queue `[ ]` 全 18 件の thumb.png を MiniMax でバッチ生成し、drip note-only を 18 回連続実行して backlog を空にする

**Architecture:** 新規 `batch_thumb_gen.py` で ①queue parse で 18 slug 抽出 ②各 slug の `articles/<slug>.md` 先頭 200 字を prompt に変換（スタイル prefix 付き） ③MCP `mcp__minimax-official__text_to_image` で 16:9 bg.jpg 生成 ④`repost_make_thumb.py` で thumb.png 合成（tag="AI"、copy=title 冒頭 15 字）。`run_drip_loop.sh` で drip note-only を 18 回排他実行。

**Tech Stack:** Python 3.12 / MCP `mcp__minimax-official__text_to_image`（image-01, 16:9, prompt_optimizer=False）/ bash / 既存 `scripts/repost_make_thumb.py` / 既存 `scripts/repost_drip_once.sh`

---

## 重要な設計前提（ふくけい承認済 2026-10-21 14:5x JST）
- 対象 = queue `[ ]` 全 18 件（`nexuscore-stage-2-architect-debugger-guardian-3`, `claude-code-tool-calling-5359933a`, `llm-cli-sync-from-ssot-sh-5-80c5343a`, `claude-code-desktop-mcp-cost-delegation`, `claude-code-desktop-mcp-cost-reduction`, `claude-code-settings-json-python-json`, `claude-code-commit-3-hook-git-commit-scop-1760a199`, `claude-code-minimax-fallback`, `claude-code-sessionstart-hook-python`, `claude-code-sessionstart-hooks-automation`, `context-engineering-47kb-tool`, `bdd-for-beginners`, `cicd-for-beginners`, `ddd-for-beginners`, `design-principles-for-beginners`, `dev-methods-selector`, `caddy-nginx-replacement-vps`, `nexuscore-multi-agent-architecture`）
- 画像プロンプト = `title + 先頭 200 字` + スタイル prefix
- tag = `"AI"` 固定 / copy = `title 冒頭 15 字に切る`（句読点・読点があれば最初の句読点で切る）

## 実装ファイル
- 新規: `~/projects/zenn/scripts/batch_thumb_gen.py`（画像生成 + thumb 合成オーケストレータ）
- 新規: `~/projects/zenn/scripts/run_drip_loop.sh`（drip note-only × 18 排他ループ）
- 既存利用: `~/projects/zenn/scripts/repost_make_thumb.py`（合成）
- 既存利用: `~/projects/zenn/scripts/repost_drip_once.sh`（note-only 経路呼び出し）
- 既存: `~/projects/zenn/repost-queue.md`（parse 対象・破壊しない）

---

### Task 1: queue parse 関数と slug 抽出の TDD

**Files:**
- Create: `~/projects/zenn/scripts/batch_thumb_gen.py`
- Create: `~/projects/zenn/tests/test_batch_thumb_gen_parse.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_batch_thumb_gen_parse.py
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
```

- [ ] **Step 2: テスト実行して失敗確認**

```bash
cd ~/projects/zenn && python3 -m pytest tests/test_batch_thumb_gen_parse.py -v
```
Expected: ModuleNotFoundError（batch_thumb_gen 未実装）

- [ ] **Step 3: 最小実装**

```python
# scripts/batch_thumb_gen.py
"""drip用thumb.png一括生成（MiniMax経由）。"""
import re
import sys
from pathlib import Path

QUEUE_PATH = Path(__file__).resolve().parent.parent / "repost-queue.md"
REPO_ROOT = QUEUE_PATH.parent


def parse_pending_slugs(queue_path: str) -> list[str]:
    """queue [ ] 行から slug を順序保持で抽出。"""
    out: list[str] = []
    pat = re.compile(r"^- \[ \] (\S+)")
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            m = pat.match(line)
            if m:
                out.append(m.group(1))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for s in parse_pending_slugs(str(QUEUE_PATH)):
            print(s)
```

- [ ] **Step 4: テスト実行して PASS 確認**

```bash
cd ~/projects/zenn && python3 -m pytest tests/test_batch_thumb_gen_parse.py -v
```
Expected: 1 passed

- [ ] **Step 5: 動作確認（queue 実際のパース）**

```bash
cd ~/projects/zenn && python3 scripts/batch_thumb_gen.py list | wc -l
```
Expected: 18

- [ ] **Step 6: 単体では commit しない（Task 6 で纏めて commit）**

---

### Task 2: article 読み込みと prompt 構築関数の TDD

**Files:**
- Modify: `~/projects/zenn/scripts/batch_thumb_gen.py`
- Create: `~/projects/zenn/tests/test_batch_thumb_gen_prompt.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_batch_thumb_gen_prompt.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import batch_thumb_gen as bg


def test_load_article_returns_title_and_head(tmp_path):
    a = tmp_path / "articles" / "sample.md"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text(
        '---\ntitle: "BDD入門"\nemoji: "🎭"\ntype: "tech"\n---\n\n## はじめに\n\n'
        + ("本文テスト用。" * 50) + "\n",
        encoding="utf-8",
    )
    title, head = bg.load_article_title_and_head(str(a), head_chars=200)
    assert title == "BDD入門"
    assert "本文テスト用" in head
    assert len(head) <= 200


def test_build_image_prompt_combines_style_prefix():
    prompt = bg.build_image_prompt(
        title="BDD入門",
        head="TDDとBDDの違いを解説する",
    )
    assert prompt.startswith("minimal flat illustration")  # style prefix 必須
    assert "BDD入門" in prompt
    assert "TDDとBDDの違い" in prompt


def test_build_thumb_copy_truncates_title_to_15_chars():
    assert bg.build_thumb_copy("Claude Code CLIにMiniMaxをフォールバックとして組み込んだ話（安いLLMを7層で守り抜く戦略）") \
        == "Claude Code CLIにM"  # 15 char
```

- [ ] **Step 2: テスト実行して失敗確認**

```bash
cd ~/projects/zenn && python3 -m pytest tests/test_batch_thumb_gen_prompt.py -v
```
Expected: AttributeError（未定義関数）

- [ ] **Step 3: 最小実装を batch_thumb_gen.py に追加**

```python
import re

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TITLE_RE = re.compile(r'^title:\s*"(.*?)"\s*$', re.MULTILINE)

STYLE_PREFIX = (
    "minimal flat illustration, vibrant accent color, modern Japanese tech blog cover, "
    "no text, no people faces, abstract iconography, soft shadows -- "
)


def load_article_title_and_head(article_path: str, head_chars: int = 200) -> tuple[str, str]:
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
    return f"{STYLE_PREFIX}title={title} | abstract={head}"


def build_thumb_copy(title: str, limit: int = 15) -> str:
    # 句読点があれば最初の句読点で切る
    for sep in ("、", "。", "（", "("):
        idx = title.find(sep)
        if 0 < idx <= limit:
            return title[:idx]
    return title[:limit]


if __name__ == "__main__":
    pass  # Task 1 の main を残す
```

- [ ] **Step 4: テスト PASS 確認**

```bash
cd ~/projects/zenn && python3 -m pytest tests/test_batch_thumb_gen_prompt.py -v
```
Expected: 3 passed

- [ ] **Step 5: 既存 article で実値確認**

```bash
cd ~/projects/zenn && python3 -c "
import batch_thumb_gen as bg
title, head = bg.load_article_title_and_head('articles/bdd-for-beginners.md', 200)
print('TITLE:', repr(title))
print('HEAD:', repr(head))
print('PROMPT:', repr(bg.build_image_prompt(title, head)[:120]))
print('COPY:', repr(bg.build_thumb_copy(title)))
"
```
Expected: TITLE=BDD..., HEAD=<本文先頭>, PROMPT=minimal flat illustration..., COPY=<15字以内>

---

### Task 3: 1 slug 分の画像生成 + thumb 合成オーケストレータ関数の TDD

**Files:**
- Modify: `~/projects/zenn/scripts/batch_thumb_gen.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_batch_thumb_gen_orchestrate.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import batch_thumb_gen as bg


def test_process_slug_skips_when_thumb_png_exists(tmp_path, monkeypatch):
    slug = "skip-me"
    art = tmp_path / "articles" / f"{slug}.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text('---\ntitle: "skip"\n---\n\nbody\n', encoding="utf-8")
    repo = tmp_path
    mdir = repo / "repost-manuscripts" / slug
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "thumb.png").write_bytes(b"already")
    # image 関数が呼ばれないことを monkeypatch で確認
    called = []
    monkeypatch.setattr(bg, "_image_to_path", lambda *a, **k: called.append(a) or "x")
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "ARTICLES_DIR", repo / "articles")
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
    monkeypatch.setattr(bg, "REPO_ROOT", repo)
    monkeypatch.setattr(bg, "_image_to_path",
        lambda prompt, out: _fake_jpg(out))
    monkeypatch.setattr(bg, "_compose_thumb",
        lambda slug, repo_root: (repo_root / "repost-manuscripts" / slug / "thumb.png").write_bytes(b"thumb"))
    bg.process_slug(slug)
    assert (repo / "repost-manuscripts" / slug / "thumb.png").exists()


def _fake_jpg(path: str) -> str:
    # 1x1 JPEG minimal
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb0043000302020303020303030304030304050805"
            "0504040405050a06060a09090a09090909090909090909090909090909090909090909090909090909"
            "0909ffd9"))
    return path
```

- [ ] **Step 2: 失敗確認**

```bash
cd ~/projects/zenn && python3 -m pytest tests/test_batch_thumb_gen_orchestrate.py -v
```
Expected: AttributeError

- [ ] **Step 3: オーケストレータ実装を batch_thumb_gen.py に追加**

```python
ARTICLES_DIR = REPO_ROOT / "articles"
MANUSCRIPTS_DIR = REPO_ROOT / "repost-manuscripts"


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
    if not bg_path.exists():
        print(f"[batch] image gen failed: {slug}")
        return "image-failed"
    _compose_thumb(slug, REPO_ROOT)
    if not thumb.exists():
        print(f"[batch] thumb compose failed: {slug}")
        return "thumb-failed"
    print(f"[batch] OK: {slug}")
    return "ok"


def _image_to_path(prompt: str, out_jpg: str) -> str:
    """MCP mcp__minimax-official__text_to_image 呼び出し。
    test では monkeypatch でスタブ化。本番では CC が tool 経由で呼ぶ。
    戻り値は out_jpg と同義（保存先パス）。"""
    raise NotImplementedError("subprocess driver required")


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
```

- [ ] **Step 4: テスト PASS 確認**

```bash
cd ~/projects/zenn && python3 -m pytest tests/test_batch_thumb_gen_orchestrate.py -v
```
Expected: 2 passed（monkeypatch 経由のため image gen は呼ばれない）

---

### Task 4: 統合スクリプトと全 18 件ループの main 関数を追加

**Files:**
- Modify: `~/projects/zenn/scripts/batch_thumb_gen.py`

- [ ] **Step 1: main 関数追加**

```python
def main() -> int:
    slugs = parse_pending_slugs(str(QUEUE_PATH))
    if not slugs:
        print("[batch] queue empty")
        return 0
    print(f"[batch] processing {len(slugs)} slugs: {slugs}")
    results: dict[str, str] = {}
    for i, slug in enumerate(slugs, 1):
        print(f"[batch] ({i}/{len(slugs)}) {slug}")
        try:
            results[slug] = process_slug(slug)
        except Exception as e:
            print(f"[batch] exception: {slug}: {e}")
            results[slug] = "exception"
    # 集約レポート
    summary = {}
    for k, v in results.items():
        summary[v] = summary.get(v, 0) + 1
    print(f"[batch] SUMMARY: {summary}")
    failed = [k for k, v in results.items() if v != "ok" and v != "skipped"]
    if failed:
        print(f"[batch] FAILED: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for s in parse_pending_slugs(str(QUEUE_PATH)):
            print(s)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "process":
        sys.exit(main())
    sys.exit(0)
```

- [ ] **Step 2: list で 18 件出ること再確認**

```bash
cd ~/projects/zenn && python3 scripts/batch_thumb_gen.py list | wc -l
```
Expected: 18

- [ ] **Step 3: process ドライラン（画像生成は本Task 6 で実行）**

```bash
cd ~/projects/zenn && python3 -c "
import batch_thumb_gen as bg
print('module loads OK')
print('parse:', len(bg.parse_pending_slugs(str(bg.QUEUE_PATH))))
"
```
Expected: 出力のみ・EXIT=0

---

### Task 5: 最初の 3 件で MCP 画像生成パイロット実行（小規模テスト・ふくけい確認用）

**Files:** なし（既存 repost-manuscripts への書き込みのみ）

> **ふくけい承認 2026-10-21 14:5x JST**: 全 18 件一気に入れず、最初の 3 件で品質確認後に残り 15 件へ進む。

- [ ] **Step 1: 既存 thumb.png の有無確認**

```bash
cd ~/projects/zenn && python3 -c "
import pathlib
for slug in $(python3 scripts/batch_thumb_gen.py list):
    p = pathlib.Path('repost-manuscripts') / slug / 'thumb.png'
    print(('EXISTS' if p.exists() else 'MISSING'), slug)
" | head -3
```
Expected: 3 行とも `MISSING <slug>`

- [ ] **Step 2: 1 件目の slug を取得**

```bash
cd ~/projects/zenn && python3 scripts/batch_thumb_gen.py list | head -1
```
Expected: `nexuscore-stage-2-architect-debugger-guardian-3`

- [ ] **Step 3: プロンプト生成を確認**

```bash
cd ~/projects/zenn && python3 -c "
import batch_thumb_gen as bg
slug = 'nexuscore-stage-2-architect-debugger-guardian-3'
title, head = bg.load_article_title_and_head(f'articles/{slug}.md', 200)
prompt = bg.build_image_prompt(title, head)
copy = bg.build_thumb_copy(title)
print('SLUG:', slug)
print('TITLE:', title)
print('COPY:', copy)
print('PROMPT_LEN:', len(prompt))
print('PROMPT_HEAD:', prompt[:80])
"
```
Expected: TITLE/COPY/PROMPT_LEN が表示。PROMPT は `minimal flat illustration...` で始まる。

- [ ] **Step 4: 1 件目: MiniMax MCP で画像生成（CC が直接 tool 呼び出し）**

```
mcp__minimax-official__text_to_image(
  prompt=<Task 6 Step 3 の PROMPT_FULL>,
  aspect_ratio="16:9",
  n=1,
  prompt_optimizer=False,
  output_directory="/home/yn4416/projects/zenn/repost-manuscripts/nexuscore-stage-2-architect-debugger-guardian-3"
)
```
戻り値の file_path を `repost-manuscripts/nexuscore-stage-2-architect-debugger-guardian-3/bg.jpg` へコピー

- [ ] **Step 5: 1 件目: thumb.png 合成**

```bash
cd ~/projects/zenn && python3 scripts/repost_make_thumb.py \
  repost-manuscripts/nexuscore-stage-2-architect-debugger-guardian-3/bg.jpg \
  repost-manuscripts/nexuscore-stage-2-architect-debugger-guardian-3/thumb.png \
  "AI" "<Task 6 Step 3 の COPY>"
```
Expected: `[make-thumb] 生成: .../thumb.png（tag=AI / copy=<COPY>）` + EXIT=0

- [ ] **Step 6: 1 件目ファイル確認**

```bash
ls -la ~/projects/zenn/repost-manuscripts/nexuscore-stage-2-architect-debugger-guardian-3/{bg.jpg,thumb.png}
```
Expected: 両方存在・bg.jpg が JPEG・thumb.png が PNG

- [ ] **Step 7: 2 件目・3 件目も Step 2-6 を同様実施**

対象 slug:
- 2 件目: `claude-code-tool-calling-5359933a`（手前で pick）
- 3 件目: `llm-cli-sync-from-ssot-sh-5-80c5343a`

各 1 件あたり所要 30-90 秒（MCP roundtrip + 画像生成待ち）

- [ ] **Step 8: 3 件完了後、ふくけいへ品質確認**

ふくけいに 3 件の `thumb.png` を画像ビューアで目視確認してもらう:
- `/home/yn4416/projects/zenn/repost-manuscripts/nexuscore-stage-2-architect-debugger-guardian-3/thumb.png`
- `/home/yn4416/projects/zenn/repost-manuscripts/claude-code-tool-calling-5359933a/thumb.png`
- `/home/yn4416/projects/zenn/repost-manuscripts/llm-cli-sync-from-ssot-sh-5-80c5343a/thumb.png`

OK なら次の判断:
- A) 残り 15 件を継続実施
- B) プロンプト修正（スタイル追加・色味変更）→ Task 2 の build_image_prompt を修正して Step 4 から
- C) 中断・残 15 件は次回セッション

---

### Task 6: 残り 15 件分の画像生成継続実行（パイロット合格後）

**Files:** なし（既存 repost-manuscripts への書き込みのみ）

> Task 5 のふくけい承認が A「残り 15 件を継続実施」の場合のみ本 Task を実行。

- [ ] **Step 1: 既に生成済の slug を確認して残り 15 件を出す**

```bash
cd ~/projects/zenn && python3 -c "
import pathlib
pending = open('repost-queue.md', encoding='utf-8').read().splitlines()
import re
slugs = [m.group(1) for ln in pending for m in [re.match(r'^- \[ \] (\S+)', ln)] if m]
remaining = [s for s in slugs if not (pathlib.Path('repost-manuscripts')/s/'thumb.png').exists()]
print('remaining:', len(remaining))
for s in remaining: print(s)
"
```
Expected: 残り 15 件の slug リスト

- [ ] **Step 2: 15 件 1 件ずつ MiniMax MCP で画像生成 + thumb 合成**

Task 5 Step 4-6 を slug ごとに実施。各 30-90 秒想定。

> **省略時の代替/リスク**: API 429 発生時は 60 秒待機して 1 回リトライ → 失敗時はスキップして次へ。

- [ ] **Step 3: 18 件全件完了確認**

```bash
cd ~/projects/zenn && for s in $(python3 scripts/batch_thumb_gen.py list); do
  if [ ! -f "repost-manuscripts/$s/thumb.png" ]; then echo "MISSING: $s"; fi
done; echo "all check done"
```
Expected: MISSING 出力なし

---

### Task 7: drip note-only × 18 回 ループ script 実装

**Files:**
- Create: `~/projects/zenn/scripts/run_drip_loop.sh`

- [ ] **Step 1: 実装**

```bash
#!/usr/bin/env bash
# drip note-only を [ ] 0件になるまでループする（flock排他・冪等）
set -uo pipefail

cd ~/projects/zenn || exit 1

count() { grep -c -e '^- \[ \]' repost-queue.md; }

remaining=$(count)
i=0
while [ "$remaining" -gt 0 ]; do
  i=$((i+1))
  echo "[drip-loop] (${i}) remaining=${remaining} $(date '+%F %T')"
  # 1件処理
  bash scripts/repost_drip_once.sh note-only 2>&1 | tee -a "logs/drip-loop-$(date +%F).log"
  rc=${PIPESTATUS[0]}
  echo "[drip-loop] rc=${rc}"
  # 終了コード4/5（note投稿失敗・サムネ失敗）は一旦止める（手動対応要）
  if [ "$rc" -eq 4 ] || [ "$rc" -eq 5 ]; then
    echo "[drip-loop] abort: rc=${rc} (note失敗 or thumb失敗・手動対応要)"
    exit "$rc"
  fi
  remaining=$(count)
  # note API レート回避スリープ（10秒）
  sleep 10
done
echo "[drip-loop] queue empty・正常終了"
```

- [ ] **Step 2: 実行権限付与**

```bash
chmod +x ~/projects/zenn/scripts/run_drip_loop.sh
```

- [ ] **Step 3: dry-run**

```bash
cd ~/projects/zenn && bash -n scripts/run_drip_loop.sh && echo "syntax OK"
```
Expected: syntax OK

- [ ] **Step 4: 実行（Task 6 で thumb が揃った状態で）**

```bash
cd ~/projects/zenn && bash scripts/run_drip_loop.sh
```
Expected: 各イテレーションで `[drip] note-only 対象: <slug>` → `[drip] note-only完了: <slug>` のループ。18 件完了後 `[drip-loop] queue empty・正常終了`

---

### Task 8: run_drip_loop.sh 実行と queue 空確認

**Files:** なし（drip-loop 実行のみ・queue とログへの書き込み）

- [ ] **Step 1: dry-run**

```bash
cd ~/projects/zenn && bash -n scripts/run_drip_loop.sh && echo "syntax OK"
```
Expected: syntax OK

- [ ] **Step 2: queue 件数確認（実行前）**

```bash
cd ~/projects/zenn && grep -c -e '^- \[ \]' repost-queue.md
```
Expected: 0（thumb生成時点で queue 自体は変化しないため 18）

- [ ] **Step 3: drip-loop 実行（18 件順次処理）**

```bash
cd ~/projects/zenn && bash scripts/run_drip_loop.sh
```
Expected: 各イテレーションで `[drip] note-only 対象: <slug>` → `[drip] note-only完了: <slug>` のループ。18 件完了後 `[drip-loop] queue empty・正常終了`

> **省略時の代替/リスク**: queue に thumb 無い slug が混ざる場合は drip が exit 3 で即停止するはずだが、Task 5-7 で全件 thumb 生成済のため起こらない想定。

- [ ] **Step 4: queue 状態確認（実行後）**

```bash
cd ~/projects/zenn && grep -c -e '^- \[ \]' repost-queue.md && grep -c -e '^- \[n\]' repost-queue.md
```
Expected: `[ ]`=0 / `[n]`=18

---

### Task 9: 失敗レポートと handoff 記録

**Files:**
- Create: `~/projects/zenn/logs/batch-thumb-2026-10-21.log`（自動生成される）
- Append: `~/projects/obsidian-ssot/10_DAILY/2026-10-21.md`（セッションログ）

- [ ] **Step 1: 完了レポートをふくけいに提示**

- 18 件全件生成成功: 0 件失敗
- drip 18 件 all-success: queue 空
- 1 件以上失敗: 該当 slug を再試行 → それでも失敗なら手動対応要

- [ ] **Step 2: SSOT 記録（harness ssot-record スキル経由）**

`obsidian-ssot/01_DECISIONS/zenn/2026-10-21_drip-thumb-一括生成スクリプト実装.md` を新規作成し、`10_DAILY/2026-10-21.md` にリンク追加

- [ ] **Step 3: handoff 新規生成（次セッション用）**

`obsidian-ssot/00_SYSTEM/handoff/2026-10-21_xxxx_<session_id>.md` に現状サマリを保存

---

## 検証方針（fail条件）
- 画像生成 MiniMax API 429 / エラー → 1 slug リトライ → 失敗レポートに記録
- thumb 合成で PIL / Playwright エラー → 該当 slug スキップして次へ
- drip 連続 5 件で 1 件でも publish 失敗 → run_drip_loop.sh は exit 4 / 5 で即停止
- queue の破壊（[ ] → [x] の不正マーク）→ drip 自身が mark_queue するため、batch_thumb_gen は queue を触らない（parse のみ）

## 検証範囲宣言
- **タイプ**: II（ファイル hash = 設定/スクリプト本体）+ III（run-loop の挙動 = 設計）
- **正常系**:
  - Task 1-5: pytest 4 cases PASS（parse / prompt / compose）
  - Task 6: 18 件 bg.jpg + thumb.png ファイル存在確認
  - Task 7: drip-loop exit 0 で queue 空
- **異常系**:
  - Task 1 test_parse_queue_returns_pending_slugs（境界・[x]/[n]/[ ] 混在）
  - Task 3 test_process_slug_skips_when_thumb_png_exists（冪等性）
- **fail 条件**: drip-loop が exit 4/5 で停止する経路を Task 7 で実装

## Self-Review
- spec coverage: queue 18 件 parse → 画像生成 → thumb 合成 → drip 18 ループ全て Task で網羅
- placeholder scan: TBD/TODO 無し、すべて具体コード
- type consistency: parse_pending_slugs, build_image_prompt, build_thumb_copy, process_slug は全 Task 同一シグネチャ

---

## 運用変更記録（2026-11-26実測・prompt_optimizer=true必須化）

- **2026-11-25〜26実測**: `prompt_optimizer=false` で 21生成中1枚のみPASS（白紙・全面文字化けの2系統）・前回成功実績（2026-11-15・10/10成功）と同一promptの再現実験でも0/3 NG → **optimizer=false経路の障害と判定**（【仮説】MiniMax側のoptimizer-off生成経路に回帰・API内部は観測不能）
- **optimizer=true への切替で 10/10 PASS**（fork判読による実視認・2026-11-26実測・うち2枚に軽微な要素欠落/装飾模様ありだがサムネ水準）
- **恒久運用**: thumb生成時は `prompt_optimizer=true` を使う（PLAN当初のfalse指定は2026-10-21時点の実績に基づく・2026-11-26実測で反転）。英字prompt+日本語描き込み防止の意図はtrueでも維持実測
- cron prompt側のMiniMax text_to_image指示も同様にtrueとする
