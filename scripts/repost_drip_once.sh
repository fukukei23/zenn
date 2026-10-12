#!/usr/bin/env bash
# 転載ドリップ1回実行（12時間間隔durable cronから呼ばれる・flock排他・冪等）
# キュー: ~/projects/zenn/repost-queue.md の先頭 [ ] 行を1件消費し note+Qiita へ公開
set -uo pipefail

exec 9>/tmp/repost-drip.lock
flock -n 9 || { echo "[drip] 他実行中のためskip（flock失敗）"; exit 0; }

cd ~/projects/zenn
QUEUE=repost-queue.md
SLUG=$(grep -m1 '^- \[ \]' "$QUEUE" | sed 's/^- \[ \] //' | cut -d' ' -f1)
[ -z "$SLUG" ] && { echo "[drip] キュー空・終了"; exit 0; }
echo "[drip] 対象: $SLUG ($(date +%H:%M:%S))"

set -a; source ~/.secrets.env; set +a

# --- 1. note用へ変換 + Qiita用原稿の自動生成 ---
python3 scripts/repost_make_note.py "articles/${SLUG}.md" "repost-manuscripts/${SLUG}/note.md" || exit 1
mkdir -p "repost-manuscripts/${SLUG}"
python3 - "$SLUG" <<'PY' || exit 1
import pathlib, re, sys
slug = sys.argv[1]
src = pathlib.Path(f"articles/{slug}.md")
dst = pathlib.Path(f"repost-manuscripts/{slug}/qiita.md")
text = src.read_text(encoding="utf-8")
parts = text.split("---")
body = "---".join(parts[2:]).strip()
attr = "\n\n---\n\n本記事は[個人Zenn](https://zenn.dev/fukukei23)でも公開しています。\n"
if "個人Zenn" not in body:
    body += attr
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(body + "\n", encoding="utf-8")
print(f"[drip] qiita.md生成: {len(body)}文字")
PY

# --- 2. Qiita投稿（private→即公開切替） ---
TITLE=$(sed -n 's/^title: *"\(.*\)"/\1/p' "articles/${SLUG}.md" | head -1)
Q_OUT=$(python3 scripts/repost_qiita_post.py post "repost-manuscripts/${SLUG}/qiita.md" "AI,VibeCoding,LLM" "$TITLE" 2>&1)
echo "$Q_OUT"
if echo "$Q_OUT" | grep -q "item_id=[0-9a-f]"; then
    QID=$(echo "$Q_OUT" | grep -oE "item_id=[0-9a-f]+" | cut -d= -f2)
    sleep 10
    P_OUT=$(python3 scripts/repost_qiita_post.py publish "$QID" 2>&1)
    echo "$P_OUT"
    Q_OK=$(echo "$P_OUT" | grep -c "private=False")
else
    echo "[drip] Qiita投稿失敗（429/403想定）→ 次回cronへ持ち越し"
    exit 2
fi
[ "$Q_OK" = "1" ] || { echo "[drip] Qiita公開切替失敗"; exit 3; }

# --- 3. note投稿（自動公開） ---
NOTE_GO_FILE=/tmp/note-drip-go NOTE_AUTO_PUBLISH=1 \
  python3 scripts/repost_note_post.py "repost-manuscripts/${SLUG}/note.md" 60 2>&1 | tee /tmp/drip-note-out.txt
NOTE_EXIT=$?
[ $NOTE_EXIT -eq 0 ] || { echo "[drip] note投稿失敗（exit $NOTE_EXIT）・Qiitaは公開済み"; exit 4; }
NOTE_LAST_URL=$(grep -oE "https://editor.note.com/notes/[0-9a-f]+/publish/" <<< "$(cat /tmp/drip-note-out.txt)" | head -1)
echo "[drip] note投稿URL: $NOTE_LAST_URL"

# --- 4. サムネ後付け（repost-manuscripts/<slug>/thumb.png があれば） ---
THUMB="repost-manuscripts/${SLUG}/thumb.png"
NOTE_ID=$(grep -oE "notes/[0-9a-f]+" <<< "$NOTE_LAST_URL" | cut -d/ -f2)
if [ -f "$THUMB" ] && [ -n "$NOTE_ID" ]; then
    python3 scripts/repost_note_set_thumb.py "$NOTE_ID" "$THUMB" || echo "[drip] サムネ設定失敗（投稿自体は成功済み・継続）"
else
    echo "[drip] サムネ無し（thumb.png未生成）→ スキップ"
fi

# --- 5. キューを[x]化してURL追記 ---
python3 - "$SLUG" <<'PY'
import re, sys, pathlib
slug = sys.argv[1]
p = pathlib.Path("repost-queue.md")
lines = p.read_text(encoding="utf-8").split("\n")
for i, ln in enumerate(lines):
    if ln.startswith("- [ ] ") and ln.split(" — ")[0] == f"- [ ] {slug}":
        lines[i] = ln.replace("- [ ] ", "- [x] ", 1)
        break
p.write_text("\n".join(lines), encoding="utf-8")
print(f"[drip] キュー更新: {slug} を[x]化")
PY
echo "[drip] 完了: $SLUG → Qiita($QID)+note"
exit 0
