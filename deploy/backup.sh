#!/usr/bin/env bash
# Daily Postgres backup for the ProveKit stack. Dumps the DB from the running compose
# container to a gzip file, and prunes backups older than RETAIN_DAYS. Idempotent; safe to
# run from cron. Install with deploy/install-backups.sh (sets up the cron job).
#
#   BACKUP_DIR=/root/provekit-backups RETAIN_DAYS=7 bash deploy/backup.sh
set -euo pipefail

DIR="${DIR:-/root/ProveKit}"
BACKUP_DIR="${BACKUP_DIR:-/root/provekit-backups}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
DB_CONTAINER="${DB_CONTAINER:-provekit-db-1}"
DB_USER="${DB_USER:-provekit}"
DB_NAME="${DB_NAME:-provekit}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/provekit-$STAMP.sql.gz"

# pg_dump inside the container → gzip on the host.
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$OUT"
SIZE=$(du -h "$OUT" | cut -f1)
echo "$(date -Is)  backup ok: $OUT ($SIZE)"

# Prune old backups.
find "$BACKUP_DIR" -name 'provekit-*.sql.gz' -type f -mtime "+$RETAIN_DAYS" -delete
echo "$(date -Is)  kept last $RETAIN_DAYS days; $(ls "$BACKUP_DIR"/provekit-*.sql.gz 2>/dev/null | wc -l) file(s) on disk"
