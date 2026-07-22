#!/usr/bin/env bash
# Daily Postgres backup for the ProveKit stack. Dumps the DB from the running compose
# container to a gzip file, and prunes backups older than RETAIN_DAYS. Idempotent; safe to
# run from cron. Install with deploy/install-backups.sh (sets up the cron jobs).
#
#   BACKUP_DIR=/root/provekit-backups RETAIN_DAYS=7 bash deploy/backup.sh
#
# A backup is only worth what a restore proves — deploy/verify-restore.sh drills the newest
# file produced here into a throwaway database. See docs/BACKUP.md.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/provekit-backups}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
DB_CONTAINER="${DB_CONTAINER:-provekit-db-1}"
DB_USER="${DB_USER:-provekit}"
DB_NAME="${DB_NAME:-provekit}"

# `date -Is` is GNU-only; BSD/macOS date rejects it and `set -e` would kill the script at the
# log line, *after* the dump ran — the worst place to fail. Fall back to an explicit format.
ts() { date -Is 2>/dev/null || date -u "+%Y-%m-%dT%H:%M:%S+00:00"; }

# sha256sum is coreutils, shasum is what macOS ships. Either is fine; neither is guaranteed.
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum   >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else echo ""; fi
}

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/provekit-$STAMP.sql.gz"

# Dump to a .part file and only rename once the whole pipeline succeeded and gzip verifies.
# A dump killed halfway (disk full, container restart) otherwise leaves a file that looks
# exactly like a backup, and you find out it is half a database on the day you need it.
#
# --no-owner/--no-privileges: the dump has to restore into the drill database and onto a
# rebuilt host, where the role names may not match the ones that existed at dump time.
docker exec "$DB_CONTAINER" pg_dump --no-owner --no-privileges -U "$DB_USER" -d "$DB_NAME" \
  | gzip > "$OUT.part"
gzip -t "$OUT.part"
mv "$OUT.part" "$OUT"

SUM="$(sha256 "$OUT")"
[ -n "$SUM" ] && echo "$SUM  $(basename "$OUT")" > "$OUT.sha256"

SIZE=$(du -h "$OUT" | cut -f1)
BYTES=$(wc -c < "$OUT" | tr -d ' ')
echo "$(ts)  backup ok: $OUT ($SIZE, $BYTES bytes)"

# A convenience pointer for restore.sh/verify-restore.sh and for a human at 3am.
ln -sf "$(basename "$OUT")" "$BACKUP_DIR/provekit-latest.sql.gz"

# Prune old backups (dumps, their checksums, and any .part left by a crashed run).
find "$BACKUP_DIR" -name 'provekit-*.sql.gz' -type f -mtime "+$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name 'provekit-*.sql.gz.sha256' -type f -mtime "+$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name 'provekit-*.sql.gz.part' -type f -mtime +1 -delete
# -type f so the provekit-latest.sql.gz symlink isn't counted as a second copy.
KEPT=$(find "$BACKUP_DIR" -maxdepth 1 -name 'provekit-*.sql.gz' -type f | wc -l | tr -d ' ')
echo "$(ts)  kept last $RETAIN_DAYS days; $KEPT file(s) on disk"
