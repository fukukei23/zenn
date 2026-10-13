#!/usr/bin/env bash
# 転載ドリップ実行（flock排他・冪等）v3
# 使い方: repost_drip_once.sh [both|note-only|qiita-pending]
#   both          = キュー先頭を note+Qiita へ投稿（既定）
#   note-only     = キュー先頭を noteのみ投稿しキューを [n] 化
#   qiita-pending = [n]（note済/Qiita未）の記事を Qiita へ投稿して [x] 化
# スケジュール想定: 09:37 both / 13:57 note-only / 17:37 note-only / 21:37 qiita-pending
#   → note 3本/日 + Qiita 2本/日（Qiitaはレート制限429実測のため2本/日に制限）
set -uo pipefail

exec 9>/tmp/repost-drip.lock
flock -n 9 || { echo "[drip] 他実行中のためskip（flock失敗）"; exit 0; }

cd ~/projects/zenn
QUEUE=repost-queue.md
MODE="${1:-both}"
set -a; source ~/.secrets.env; set +a

log() { echo "[drip] $*"; }

get_slug_by_state() {
  grep -m1 "^- ${1}" "$QUEUE" | sed "s/^- ${1} //" | cut -d' ' -f1
}

gen_note_manuscripts() {
  local slug="$1"
  python3 scripts/repost_make_note.py "articles/${slug}.md" "repost-manuscripts/${slug}/note.md" || return 1
  mkdir -p "repost-manuscripts/${slug}"
  python3 - "$slug" <<'PY' || return 1
import pathlib, sys
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
}

gen_title() {
  sed -n 's/^title: *"\(.*\)"/\1/p' "articles/$1.md" | head -1
}

note_post() {
  local slug="$1"
  python3 scripts/repost_make_note.py "articles/${slug}.md" "repost-manuscripts/${slug}/note.md" || return 1
  NOTE_GO_FILE=/tmp/note-drip-go NOTE_AUTO_PUBLISH=1 \
    python3 scripts/repost_note_post.py "repost-manuscripts/${slug}/note.md" 60 2>&1 | tee /tmp/drip-note-out.txt
  return ${PIPESTATUS[0]}
}

note_thumb() {
  local slug="$1"
  local nurl nid thumb
  nurl=$(grep -oE "https://editor.note.com/notes/n[0-9a-f]+/publish/" /tmp/drip-note-out.txt | head -1)
  nid=$(grep -oE "notes/n[0-9a-f]+" <<< "$nurl" | head -1 | cut -d/ -f2)
  thumb="repost-manuscripts/${slug}/thumb.png"
  if [ -f "$thumb" ] && [ -n "$nid" ]; then
    # note_post直後は同一PlaywrightプロファイルのSingletonLock解放待ち（2026-10-13実測:
    # 直後起動だとセット失敗しサムネ無しで公開されるため sleep+2回リトライ・フルログ保存）
    sleep 5
    local tlog="/tmp/drip-setthumb-${nid}.log" rc
    python3 scripts/repost_note_set_thumb.py "$nid" "$thumb" 2>&1 | tee "$tlog"
    rc=${PIPESTATUS[0]}
    if [ "$rc" -eq 0 ]; then
      log "サムネ設定成功: $nid"
      return 0
    fi
    sleep 15
    python3 scripts/repost_note_set_thumb.py "$nid" "$thumb" 2>&1 | tee -a "$tlog"
    rc=${PIPESTATUS[0]}
    if [ "$rc" -eq 0 ]; then
      log "サムネ設定成功（2回目）: $nid"
      return 0
    fi
    log "サムネ設定失敗（継続・rc=$rc・ログ: $tlog）"
  else
    log "サムネスキップ（thumb存在=$([ -f "$thumb" ] && echo yes || echo no) / nid=${nid:-空}）"
  fi
}

qiita_post() {
  local slug="$1"
  local title
  title=$(gen_title "$slug")
  local out
  out=$(python3 scripts/repost_qiita_post.py post "repost-manuscripts/${slug}/qiita.md" "AI,VibeCoding,LLM" "$title" 2>&1)
  echo "$out"
  if echo "$out" | grep -q "item_id=[0-9a-f]"; then
    local qid
    qid=$(echo "$out" | grep -oE "item_id=[0-9a-f]+" | cut -d= -f2)
    sleep 10
    python3 scripts/repost_qiita_post.py publish "$qid" 2>&1
    echo "$qid"
  else
    return 1
  fi
}

mark_queue() {
  python3 - "$1" "$2" "$3" "${4:-}" <<'PY'
import sys, pathlib
slug, old, new, url = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path("repost-queue.md")
lines = p.read_text(encoding="utf-8").split("\n")
for i, ln in enumerate(lines):
    if ln.startswith("- " + old) and f" {slug} " in f" {ln} ":
        extra = f" {url}" if url else ""
        body_part = ln.split("—", 1)[1] if "—" in ln else ""
        lines[i] = f"- {new} {slug}{extra} —{body_part}"
        break
p.write_text("\n".join(lines), encoding="utf-8")
print(f"[drip] キュー更新: {slug} → {new}")
PY
}

case "$MODE" in
  note-only)
    SLUG=$(get_slug_by_state '\[ \]')
    [ -z "$SLUG" ] && { log "キュー空・終了"; exit 0; }
    log "note-only 対象: $SLUG"
    note_post "$SLUG" || { log "note投稿失敗"; exit 4; }
    note_thumb "$SLUG"
    mark_queue "$SLUG" "[ ]" "[n]"
    log "note-only完了: $SLUG"
    exit 0
    ;;
  qiita-pending)
    SLUG=$(get_slug_by_state '\[n\]')
    [ -z "$SLUG" ] && { log "Qiita未完の記事なし・終了"; exit 0; }
    log "qiita-pending 対象: $SLUG"
    gen_note_manuscripts "$SLUG"
    QID=$(qiita_post "$SLUG") || { log "Qiita失敗→次回へ"; exit 2; }
    mark_queue "$SLUG" "[n]" "[x]" "Qiita=$QID"
    log "Qiita完了: $SLUG ($QID)"
    exit 0
    ;;
  both)
    SLUG=$(get_slug_by_state '\[ \]')
    [ -z "$SLUG" ] && { log "キュー空・終了"; exit 0; }
    log "both 対象: $SLUG"
    gen_note_manuscripts "$SLUG"
    QID=$(qiita_post "$SLUG") || { log "Qiita失敗→noteのみ継続"; QID=""; }
    note_post "$SLUG" || { log "note投稿失敗"; exit 4; }
    note_thumb "$SLUG"
    if [ -n "$QID" ]; then
      mark_queue "$SLUG" "[ ]" "[x]" "Qiita=$QID note=https://note.com/fukukei23/n/$(grep -oE 'notes/n[0-9a-f]+' <<< "$(cat /tmp/drip-note-out.txt)" | head -1 | cut -d/ -f2)"
    else
      mark_queue "$SLUG" "[ ]" "[n]"
    fi
    log "both完了: $SLUG (Qiita=${QID:-未})"
    exit 0
    ;;
  *)
    echo "不明モード: $MODE"
    exit 64
    ;;
esac
