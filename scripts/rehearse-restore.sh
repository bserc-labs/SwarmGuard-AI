#!/bin/sh
# An untested backup is a hypothesis. This tests it:
#
#   1. take a fresh dump (backup.sh --once)
#   2. restore it into a scratch database (restore.sh --into ..._rehearsal)
#   3. compare, table by table, with the live database
#   4. check the hypertable survived as a hypertable, with its chunks
#   5. drop the scratch database, and report how long the restore took
#
#   docker compose run --rm backup /scripts/rehearse-restore.sh [--allow-drift]
#
# Exit 0 only if every check passed. The wall-clock time of step 2 is the
# restore half of the RTO; it is printed so it can be written down.
#
# --allow-drift: on a live system rows arrive between the dump and the compare,
# so telemetry counts differ legitimately. With the flag a table that has MORE
# rows live than restored is reported and not failed; fewer, or missing, still
# fails. CI runs without it -- nothing writes there, so the counts must match.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${BACKUP_DIR:-/backups}"
SOURCE="${PGDATABASE:?PGDATABASE is not set}"
SCRATCH="${REHEARSAL_DB:-${SOURCE}_rehearsal}"
ALLOW_DRIFT=false
[ "${1:-}" = "--allow-drift" ] && ALLOW_DRIFT=true

if [ -n "${PGPASSWORD_FILE:-}" ] && [ -s "$PGPASSWORD_FILE" ]; then
  PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
  export PGPASSWORD
fi

q() { psql -d "$1" -v ON_ERROR_STOP=1 -Atq -c "$2"; }

cleanup() {
  psql -d postgres -q -c "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[rehearsal] 1/5 fresh dump"
"$HERE/backup.sh" --once
DUMP="$(ls -1 "$DIR"/*.dump | sort | tail -n 1)"

echo "[rehearsal] 2/5 restore into $SCRATCH"
started=$(date +%s)
"$HERE/restore.sh" --dump "$DUMP" --into "$SCRATCH"
restore_seconds=$(( $(date +%s) - started ))

echo "[rehearsal] 3/5 compare"
failures=0
tables="$(q "$SOURCE" "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")"
printf '    %-28s %10s %10s\n' table live restored
for t in $tables; do
  live=$(q "$SOURCE" "SELECT count(*) FROM \"$t\"")
  if ! restored=$(q "$SCRATCH" "SELECT count(*) FROM \"$t\"" 2>/dev/null); then
    printf '    %-28s %10s %10s  MISSING\n' "$t" "$live" "-"
    failures=$((failures + 1))
    continue
  fi
  if [ "$live" = "$restored" ]; then
    printf '    %-28s %10s %10s\n' "$t" "$live" "$restored"
  elif $ALLOW_DRIFT && [ "$live" -gt "$restored" ]; then
    printf '    %-28s %10s %10s  drift (rows arrived after the dump)\n' "$t" "$live" "$restored"
  else
    printf '    %-28s %10s %10s  MISMATCH\n' "$t" "$live" "$restored"
    failures=$((failures + 1))
  fi
done

live_rev=$(q "$SOURCE" "SELECT version_num FROM alembic_version")
restored_rev=$(q "$SCRATCH" "SELECT version_num FROM alembic_version")
if [ "$live_rev" != "$restored_rev" ]; then
  echo "    alembic_version differs: live $live_rev, restored $restored_rev"
  failures=$((failures + 1))
fi

echo "[rehearsal] 4/5 hypertable"
is_hyper=$(q "$SCRATCH" "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='telemetry_logs'")
live_chunks=$(q "$SOURCE" "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name='telemetry_logs'")
restored_chunks=$(q "$SCRATCH" "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name='telemetry_logs'")
if [ "$is_hyper" != "1" ]; then
  echo "    telemetry_logs is NOT a hypertable after restore"
  failures=$((failures + 1))
elif [ "$live_chunks" != "$restored_chunks" ] && ! $ALLOW_DRIFT; then
  echo "    chunk count differs: live $live_chunks, restored $restored_chunks"
  failures=$((failures + 1))
else
  echo "    telemetry_logs is a hypertable with $restored_chunks chunk(s) (live: $live_chunks)"
fi

echo "[rehearsal] 5/5 drop $SCRATCH"
cleanup
trap - EXIT

size=$(wc -c < "$DUMP" | tr -d ' ')
echo "[rehearsal] dump $(basename "$DUMP"): $size bytes; restore took ${restore_seconds}s"
if [ "$failures" -eq 0 ]; then
  echo "[rehearsal] PASS"
else
  echo "[rehearsal] FAIL: $failures problem(s)" >&2
  exit 1
fi
