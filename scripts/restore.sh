#!/bin/sh
# Restore a dump the TimescaleDB way. Runs where pg_restore and the dumps are:
#
#   docker compose run --rm backup /scripts/restore.sh --into swarmguard_scratch
#   docker compose run --rm backup /scripts/restore.sh --dump /backups/x.dump --yes
#
#   --dump FILE   which dump; default: the newest in BACKUP_DIR
#   --into NAME   the database to (re)create; default: PGDATABASE, the live one
#   --yes         required to overwrite the live database
#
# A plain `pg_restore` into a database with the timescaledb extension either
# fails or leaves a catalogue that looks fine until the first chunk is touched.
# TimescaleDB needs to be told a restore is happening: timescaledb_pre_restore()
# before, timescaledb_post_restore() after, in a fresh database that already has
# the extension. Every step is ON_ERROR_STOP -- a half-restored database that
# reports success is worse than one that reports failure.
#
# The target is dropped and recreated. For the live database, stop the API
# first (`docker compose stop backend`): its connections would be killed
# mid-request otherwise, and it must start against the finished result.
set -eu

DIR="${BACKUP_DIR:-/backups}"
DUMP=""
TARGET="${PGDATABASE:?PGDATABASE is not set}"
YES=false

while [ $# -gt 0 ]; do
  case "$1" in
    --dump) DUMP="$2"; shift 2 ;;
    --into) TARGET="$2"; shift 2 ;;
    --yes)  YES=true; shift ;;
    *) echo "usage: $0 [--dump FILE] [--into DBNAME] [--yes]" >&2; exit 2 ;;
  esac
done

if [ -z "$DUMP" ]; then
  DUMP="$(ls -1 "$DIR"/*.dump 2>/dev/null | sort | tail -n 1 || true)"
  [ -n "$DUMP" ] || { echo "[restore] no dump in $DIR" >&2; exit 1; }
fi
[ -s "$DUMP" ] || { echo "[restore] $DUMP does not exist or is empty" >&2; exit 1; }
case "$DUMP" in *.partial) echo "[restore] $DUMP is an unfinished dump" >&2; exit 1 ;; esac

if [ "$TARGET" = "$PGDATABASE" ] && [ "$YES" != true ]; then
  echo "[restore] refusing to overwrite the live database '$TARGET' without --yes." >&2
  echo "[restore] To try the dump first: --into ${TARGET}_scratch" >&2
  exit 1
fi

if [ -n "${PGPASSWORD_FILE:-}" ] && [ -s "$PGPASSWORD_FILE" ]; then
  PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
  export PGPASSWORD
fi

# The maintenance database: the target is about to not exist.
admin() { psql -d postgres -v ON_ERROR_STOP=1 -q "$@"; }
target() { psql -d "$TARGET" -v ON_ERROR_STOP=1 -q "$@"; }

on_failure() {
  status=$?
  [ "$status" -eq 0 ] && return
  if [ "$TARGET" != "$PGDATABASE" ]; then
    # A scratch database that is half restored is worse than none: someone
    # compares against it later and trusts the numbers.
    admin -c "DROP DATABASE IF EXISTS \"$TARGET\" WITH (FORCE)" >/dev/null 2>&1 || true
    echo "[restore] FAILED; the incomplete database '$TARGET' has been dropped" >&2
  else
    echo "[restore] FAILED; '$TARGET' is INCOMPLETE. Do not start the API against it." >&2
    echo "[restore] Restore another dump with --yes, or recover the volume from elsewhere." >&2
  fi
  exit "$status"
}
trap on_failure EXIT

echo "[restore] $(basename "$DUMP") -> $TARGET"
admin -c "DROP DATABASE IF EXISTS \"$TARGET\" WITH (FORCE)"
admin -c "CREATE DATABASE \"$TARGET\""
target -c "CREATE EXTENSION IF NOT EXISTS timescaledb"
target -c "SELECT timescaledb_pre_restore()" >/dev/null
# --no-owner / --no-privileges: the restoring role owns everything, so a dump
# taken under one superuser name restores under another. --exit-on-error: the
# default is to carry on past errors and exit 0 with a partial database.
pg_restore -d "$TARGET" --no-owner --no-privileges --exit-on-error "$DUMP"
target -c "SELECT timescaledb_post_restore()" >/dev/null
echo "[restore] done"
