#!/bin/sh
# Is there a recent, complete dump? Exit 0 if so, 1 if not, with one line why.
#
#   docker compose run --rm backup /scripts/check-backups.sh
#
# For a cron job or a monitor: a backup loop that has been failing quietly for
# a week looks, from the outside, exactly like one that is working. This is
# the outside view. "Recent" is twice the backup interval, so one missed run
# is tolerated and two are not.
set -eu

DIR="${BACKUP_DIR:-/backups}"
INTERVAL="${BACKUP_INTERVAL_S:-21600}"
MAX_AGE=$(( INTERVAL * 2 ))

newest="$(ls -1 "$DIR"/*.dump 2>/dev/null | sort | tail -n 1 || true)"
if [ -z "$newest" ]; then
  echo "NO BACKUPS in $DIR"
  exit 1
fi

# The timestamp is in the file name (UTC), so this needs no stat portability.
stamp="$(basename "$newest" .dump | sed 's/.*-\([0-9]\{8\}T[0-9]\{6\}\)Z$/\1/')"
# 20260921T230528 -> "2026-09-21 23:05:28", which both busybox/GNU date -d and
# BSD date -f understand.
iso="$(echo "$stamp" | sed 's/\(....\)\(..\)\(..\)T\(..\)\(..\)\(..\)/\1-\2-\3 \4:\5:\6/')"
if ! taken=$(date -u -d "$iso" +%s 2>/dev/null) && \
   ! taken=$(date -u -j -f "%Y-%m-%d %H:%M:%S" "$iso" +%s 2>/dev/null); then
  echo "UNREADABLE timestamp in $(basename "$newest")"
  exit 1
fi
age=$(( $(date -u +%s) - taken ))
size=$(wc -c < "$newest" | tr -d ' ')

if [ "$size" -lt 1024 ]; then
  echo "SUSPICIOUS: newest dump $(basename "$newest") is only $size bytes"
  exit 1
fi
if [ "$age" -gt "$MAX_AGE" ]; then
  echo "STALE: newest dump $(basename "$newest") is ${age}s old (limit ${MAX_AGE}s)"
  exit 1
fi
echo "OK: $(basename "$newest"), ${age}s old, $size bytes"
