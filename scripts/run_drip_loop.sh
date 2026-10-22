#!/usr/bin/env bash
# drip note-only を [ ] 0件になるまでループ実行（2026-10-23 L1164 Task7）
# flock排他は repost_drip_once.sh 内蔵（/tmp/repost-drip.lock）・cronと競合しても先着側が勝つ
set -uo pipefail

cd ~/projects/zenn || exit 1
mkdir -p logs

count() { grep -c -e '^- \[ \]' repost-queue.md; }

remaining=$(count)
i=0
while [ "$remaining" -gt 0 ]; do
  i=$((i+1))
  echo "[drip-loop] (${i}) remaining=${remaining} $(date '+%F %T')"
  set -o pipefail
  bash scripts/repost_drip_once.sh note-only 2>&1 | tee -a "logs/drip-loop-$(date +%F).log"
  rc=${PIPESTATUS[0]}
  echo "[drip-loop] rc=${rc}"
  if [ "$rc" -eq 4 ] || [ "$rc" -eq 5 ]; then
    echo "[drip-loop] abort: rc=${rc}（note失敗 or サムネ失敗・手動対応要）"
    exit "$rc"
  fi
  remaining=$(count)
  sleep 10
done
echo "[drip-loop] queue empty・正常終了"
