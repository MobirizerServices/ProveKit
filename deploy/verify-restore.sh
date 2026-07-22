#!/usr/bin/env bash
# The restore drill. Restores the newest backup into a THROWAWAY database, asserts the result
# is a real ProveKit database, then drops it. Never touches the live database.
#
#   bash deploy/verify-restore.sh                 # newest dump in BACKUP_DIR
#   DUMP=/path/x.sql.gz bash deploy/verify-restore.sh
#
# Exit 0 = the backup you are holding can actually bring the product back. Exit non-zero =
# find out now, not during an incident. Installed as a weekly cron by install-backups.sh.
#
# Env: BACKUP_DIR DB_CONTAINER DB_USER DB_NAME BACKEND_CONTAINER
#      EXPECT_HEAD      alembic revision the restore must land on (default: ask the backend
#                       container, else compare against the live database)
#      MAX_AGE_HOURS    fail if the newest backup is older than this (default 36) — the drill
#                       is also the only thing that notices the backup cron died
#      MIN_ROWS         minimum rows in runs/workspaces (default 1)
#      MIN_BYTES        minimum dump size (default 1024)
#      KEEP=1           leave the drill database behind for inspection after a failure
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/provekit-backups}"
DB_CONTAINER="${DB_CONTAINER:-provekit-db-1}"
DB_USER="${DB_USER:-provekit}"
DB_NAME="${DB_NAME:-provekit}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-provekit-backend-1}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
MIN_ROWS="${MIN_ROWS:-1}"
MIN_BYTES="${MIN_BYTES:-1024}"
KEEP="${KEEP:-0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Tables that must exist for the product to function. Not the whole schema — that is checked
# separately against the live database — but the ones whose absence means "this dump is not a
# ProveKit database", which is what an empty or wrong-database backup looks like.
CORE_TABLES="alembic_version workspaces users runs api_keys workspace_members"

ts() { date -Is 2>/dev/null || date -u "+%Y-%m-%dT%H:%M:%S+00:00"; }
psql_() { docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" "$@"; }

FAILURES=0
ok()   { echo "  ok    $*"; }
fail() { echo "  FAIL  $*"; FAILURES=$((FAILURES + 1)); }
die()  { echo "$(ts)  drill ABORTED: $*" >&2; exit 2; }

# ---------------------------------------------------------------- pick the dump
DUMP="${DUMP:-}"
if [ -z "$DUMP" ]; then
  DUMP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'provekit-*.sql.gz' -type f -print0 2>/dev/null \
          | xargs -0 ls -t 2>/dev/null | head -1 || true)"
fi
[ -n "$DUMP" ] && [ -f "$DUMP" ] || die "no backup to drill (looked in $BACKUP_DIR)"

echo "$(ts)  drill start: $DUMP"

# Age. A drill that passes every week against the same six-month-old file proves the restore
# path works and hides the fact that you have been losing data since March.
NOW=$(date +%s)
MTIME=$(stat -c %Y "$DUMP" 2>/dev/null || stat -f %m "$DUMP")
AGE_H=$(( (NOW - MTIME) / 3600 ))
if [ "$AGE_H" -le "$MAX_AGE_HOURS" ]; then ok "backup is ${AGE_H}h old (limit ${MAX_AGE_HOURS}h)"
else fail "backup is ${AGE_H}h old — older than the ${MAX_AGE_HOURS}h limit; is the backup cron running?"; fi

BYTES=$(wc -c < "$DUMP" | tr -d ' ')
if [ "$BYTES" -ge "$MIN_BYTES" ]; then ok "dump is $BYTES bytes"
else fail "dump is only $BYTES bytes (< $MIN_BYTES) — almost certainly a failed pg_dump"; fi

# ---------------------------------------------------------------- restore into a scratch db
DRILL_DB="provekit_drill_$(date -u +%Y%m%d%H%M%S)_$$"
cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "$(ts)  KEEP=1: leaving '$DRILL_DB' in place"
    return
  fi
  psql_ -d postgres -c \
    "select pg_terminate_backend(pid) from pg_stat_activity where datname='$DRILL_DB' and pid<>pg_backend_pid()" \
    >/dev/null 2>&1 || true
  psql_ -d postgres -c "drop database if exists \"$DRILL_DB\"" >/dev/null 2>&1 || true
}
# Trap before the restore so an interrupted drill still cleans up its scratch database —
# otherwise a failed run leaves a full copy of production on the same disk as production.
trap cleanup EXIT INT TERM

BACKUP_DIR="$BACKUP_DIR" DB_CONTAINER="$DB_CONTAINER" DB_USER="$DB_USER" \
  bash "$HERE/restore.sh" "$DUMP" --into "$DRILL_DB" || die "restore.sh failed on $DUMP"

q() { psql_ -d "$DRILL_DB" -tAc "$1" 2>/dev/null | tr -d ' ' ; }

# ---------------------------------------------------------------- assertions
echo "$(ts)  asserting"

for t in $CORE_TABLES; do
  if [ "$(q "select count(*) from pg_tables where schemaname='public' and tablename='$t'")" = "1" ]
  then ok "table $t present"
  else fail "table $t MISSING from the restored database"; fi
done

# Row counts. A dump of an empty database restores perfectly and proves nothing.
for t in runs workspaces; do
  N="$(q "select count(*) from $t" || echo 0)"
  if [ "${N:-0}" -ge "$MIN_ROWS" ]; then ok "$t has $N row(s)"
  else fail "$t has ${N:-0} row(s) (< $MIN_ROWS) — the backup carries no data"; fi
done

# Alembic version. The restored schema must be at the revision the running code expects;
# a dump taken mid-migration, or from a database someone rebuilt by hand, will not be.
GOT_HEAD="$(q "select version_num from alembic_version" || true)"
ROWS="$(q "select count(*) from alembic_version" || echo 0)"
[ "$ROWS" = "1" ] || fail "alembic_version has $ROWS rows (expected exactly 1)"

WANT_HEAD="${EXPECT_HEAD:-}"
SRC="EXPECT_HEAD"
if [ -z "$WANT_HEAD" ]; then
  # `alembic heads` in the backend image is the truth for the code that is deployed.
  WANT_HEAD="$(docker exec "$BACKEND_CONTAINER" alembic heads 2>/dev/null \
               | awk '/\(head\)/{print $1; exit}' || true)"
  SRC="$BACKEND_CONTAINER alembic heads"
fi
if [ -z "$WANT_HEAD" ]; then
  WANT_HEAD="$(psql_ -d "$DB_NAME" -tAc "select version_num from alembic_version" 2>/dev/null | tr -d ' ' || true)"
  SRC="live database $DB_NAME"
fi
if [ -z "$WANT_HEAD" ]; then
  fail "cannot determine the expected alembic head (restored: ${GOT_HEAD:-<none>}) — set EXPECT_HEAD"
elif [ "$GOT_HEAD" = "$WANT_HEAD" ]; then
  ok "alembic_version=$GOT_HEAD matches head from $SRC"
else
  fail "alembic_version=${GOT_HEAD:-<none>} but head is $WANT_HEAD (per $SRC)"
fi

# Full schema parity against the live database, when it is reachable. Catches a table added
# by a recent migration that the dump predates, and a table silently lost in the round trip.
LIVE_TABLES="$(psql_ -d "$DB_NAME" -tAc \
  "select tablename from pg_tables where schemaname='public' order by 1" 2>/dev/null | tr -d ' ' || true)"
if [ -n "$LIVE_TABLES" ]; then
  MISSING=""
  for t in $LIVE_TABLES; do
    [ "$(q "select count(*) from pg_tables where schemaname='public' and tablename='$t'")" = "1" ] \
      || MISSING="$MISSING $t"
  done
  if [ -z "$MISSING" ]; then ok "all $(echo "$LIVE_TABLES" | wc -w | tr -d ' ') live tables present in the restore"
  else fail "tables in live but not in the restore:$MISSING"; fi
else
  echo "  skip  schema parity (live database '$DB_NAME' not reachable from $DB_CONTAINER)"
fi

# ---------------------------------------------------------------- verdict
#
# Record the verdict where a human or a monitor can see it. A cron job that stops running
# emits no failure at all — only a status file that quietly stops being updated reveals that,
# so `stat` on this file is the check worth alerting on.
if [ "$FAILURES" -eq 0 ]; then
  echo "$(ts)  PASS  $DUMP" > "$BACKUP_DIR/last-drill.txt" 2>/dev/null || true
  echo "$(ts)  drill PASSED: $DUMP restores to a working ProveKit database"
  exit 0
fi
echo "$(ts)  FAIL ($FAILURES checks)  $DUMP" > "$BACKUP_DIR/last-drill.txt" 2>/dev/null || true
echo "$(ts)  drill FAILED: $FAILURES check(s) failed on $DUMP" >&2
exit 1
