#!/usr/bin/env bash
# Restore a ProveKit Postgres dump (from deploy/backup.sh) into a database.
#
#   bash deploy/restore.sh                            # newest dump -> a NEW db, refuses to clobber
#   bash deploy/restore.sh --into provekit_scratch    # explicit target
#   bash deploy/restore.sh /path/dump.sql.gz --into provekit --force   # real recovery
#
# Env: BACKUP_DIR DB_CONTAINER DB_USER DB_NAME (target defaults to DB_NAME).
#
# Two rules this script exists to enforce:
#  1. It never writes into a database that already has tables unless you say --force. A
#     plain pg_dump has no DROPs, so restoring over live data silently *merges* — duplicate
#     key errors on some tables, stale rows left behind on others. That outcome is worse
#     than no restore, and it looks like success in a log.
#  2. It restores in a single transaction with ON_ERROR_STOP. Either the whole database is
#     back or nothing changed; there is no half-restored state to reason about at 3am.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/provekit-backups}"
DB_CONTAINER="${DB_CONTAINER:-provekit-db-1}"
DB_USER="${DB_USER:-provekit}"
DB_NAME="${DB_NAME:-provekit}"
FORCE="${FORCE:-0}"
DUMP=""
TARGET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --into) TARGET="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) DUMP="$1"; shift ;;
  esac
done
TARGET="${TARGET:-$DB_NAME}"

ts() { date -Is 2>/dev/null || date -u "+%Y-%m-%dT%H:%M:%S+00:00"; }
psql_() { docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" "$@"; }
die() { echo "$(ts)  restore FAILED: $*" >&2; exit 1; }

# ---------------------------------------------------------------- pick + check the dump
if [ -z "$DUMP" ]; then
  # Newest by mtime. -type f skips the provekit-latest.sql.gz symlink so we never resolve
  # to the same file twice or trip over a dangling link left by a pruned backup.
  DUMP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'provekit-*.sql.gz' -type f -print0 2>/dev/null \
          | xargs -0 ls -t 2>/dev/null | head -1 || true)"
fi
[ -n "$DUMP" ] && [ -f "$DUMP" ] || die "no dump found (looked in $BACKUP_DIR)"

gzip -t "$DUMP" || die "$DUMP is not a readable gzip file"

# Verify the checksum if backup.sh wrote one. Silent bit rot on the backup volume is the
# failure mode that a gzip test alone will not always catch.
if [ -f "$DUMP.sha256" ]; then
  WANT="$(cut -d' ' -f1 < "$DUMP.sha256")"
  if command -v sha256sum >/dev/null 2>&1; then GOT="$(sha256sum "$DUMP" | cut -d' ' -f1)"
  elif command -v shasum   >/dev/null 2>&1; then GOT="$(shasum -a 256 "$DUMP" | cut -d' ' -f1)"
  else GOT=""; fi
  [ -z "$GOT" ] || [ "$GOT" = "$WANT" ] || die "checksum mismatch on $DUMP (corrupt backup)"
fi

echo "$(ts)  restoring $DUMP -> database '$TARGET' on container $DB_CONTAINER"

# ---------------------------------------------------------------- prepare the target
EXISTS="$(psql_ -d postgres -tAc "select 1 from pg_database where datname='$TARGET'" || true)"

if [ "$EXISTS" = "1" ]; then
  TABLES="$(psql_ -d "$TARGET" -tAc \
    "select count(*) from pg_tables where schemaname='public'" || echo 0)"
  if [ "${TABLES:-0}" != "0" ] && [ "$FORCE" != "1" ]; then
    die "database '$TARGET' already has $TABLES tables. Re-run with --force to DROP and recreate it."
  fi
  if [ "${TABLES:-0}" != "0" ]; then
    echo "$(ts)  --force: dropping '$TARGET' ($TABLES tables)"
    # DROP DATABASE fails while anything is connected, and in a real recovery the app is
    # usually still up. Stop the app first if you can; this is the seatbelt for when you
    # cannot. Terminating a backend is safe here — we are about to delete the database.
    psql_ -d postgres -c \
      "select pg_terminate_backend(pid) from pg_stat_activity where datname='$TARGET' and pid<>pg_backend_pid()" \
      >/dev/null
    psql_ -d postgres -c "drop database \"$TARGET\"" >/dev/null
    EXISTS=""
  fi
fi
[ "$EXISTS" = "1" ] || psql_ -d postgres -c "create database \"$TARGET\" owner \"$DB_USER\"" >/dev/null

# ---------------------------------------------------------------- restore
# --single-transaction + ON_ERROR_STOP: all or nothing (see rule 2 above).
gunzip -c "$DUMP" | psql_ -d "$TARGET" --single-transaction -q >/dev/null \
  || die "psql rejected the dump (nothing was applied)"

VER="$(psql_ -d "$TARGET" -tAc "select version_num from alembic_version" || true)"
TBL="$(psql_ -d "$TARGET" -tAc "select count(*) from pg_tables where schemaname='public'")"
echo "$(ts)  restore ok: '$TARGET' has $TBL tables, alembic_version=${VER:-<none>}"
