#!/bin/sh
# Runs inside the `backup` service: a compressed pg_dump on a schedule, pruned
# by age. It is the same image as postgres so pg_dump and the server are always
# the same version.
#
#   backup.sh              loop forever: dump, prune, sleep BACKUP_INTERVAL_S
#   backup.sh --once       one dump and one prune, then exit (CI, cron, by hand)
#
# Environment:
#   PGHOST PGUSER PGDATABASE   what to dump
#   PGPASSWORD_FILE            the postgres_password secret
#   BACKUP_DIR                 where dumps go (a volume or a host directory)
#   BACKUP_INTERVAL_S          default 21600 (6 h) -- this is the RPO
#   BACKUP_RETAIN_DAYS         default 14
#
# Custom format (-Fc): compressed, and pg_restore can pick tables out of it.
# Written to a temp name and renamed, so a dump interrupted mid-write never
# looks like a complete one. The restore side is scripts/restore.sh, which does
# the TimescaleDB pre/post-restore dance a plain pg_restore would get wrong.
set -eu

DIR="${BACKUP_DIR:-/backups}"
INTERVAL="${BACKUP_INTERVAL_S:-21600}"
RETAIN="${BACKUP_RETAIN_DAYS:-14}"
PREFIX="${BACKUP_PREFIX:-swarmguard}"

if [ -n "${PGPASSWORD_FILE:-}" ] && [ -s "$PGPASSWORD_FILE" ]; then
  PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
  export PGPASSWORD
fi

mkdir -p "$DIR"

dump_once() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  final="$DIR/$PREFIX-$stamp.dump"
  partial="$final.partial"
  started=$(date +%s)
  if pg_dump -Fc --no-password -f "$partial" "$PGDATABASE"; then
    mv "$partial" "$final"
    size=$(wc -c < "$final" | tr -d ' ')
    echo "[backup] wrote $(basename "$final") ($size bytes, $(( $(date +%s) - started )) s)"
  else
    rm -f "$partial"
    echo "[backup] ERROR: pg_dump failed; no file written" >&2
    return 1
  fi
}

prune() {
  # -mtime +N is "more than N*24h old". Only complete dumps; never a .partial
  # someone may be looking at, and never anything not ours.
  find "$DIR" -maxdepth 1 -name "$PREFIX-*.dump" -type f -mtime +"$RETAIN" -print | while read -r old; do
    rm -f "$old"
    echo "[backup] pruned $(basename "$old") (older than $RETAIN days)"
  done
}

if [ "${1:-}" = "--once" ]; then
  dump_once
  prune
  exit 0
fi

echo "[backup] every ${INTERVAL}s, keeping ${RETAIN} days, in $DIR"
while :; do
  # A failed dump must not stop the loop: the next attempt may succeed, and a
  # container that exits is one that stops trying. The error is in the log,
  # and scripts/check-backups.sh turns "no fresh dump" into a non-zero exit.
  dump_once || true
  prune
  sleep "$INTERVAL"
done
