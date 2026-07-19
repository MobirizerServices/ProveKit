#!/usr/bin/env bash
# Install the daily ProveKit DB backup cron job (runs deploy/backup.sh at 03:15 daily).
# Run once on the VPS as root:  bash deploy/install-backups.sh
set -euo pipefail
DIR="${DIR:-/root/ProveKit}"
LINE="15 3 * * * BACKUP_DIR=/root/provekit-backups RETAIN_DAYS=7 bash $DIR/deploy/backup.sh >> /var/log/provekit-backup.log 2>&1"

# Replace any existing ProveKit backup cron line, then add ours. `|| true` so an empty
# crontab (grep finds nothing → exit 1) doesn't abort under `set -e`.
( crontab -l 2>/dev/null | grep -v 'deploy/backup.sh' || true ; echo "$LINE" ) | crontab -
echo "installed cron:"
crontab -l | grep backup.sh
echo "log: /var/log/provekit-backup.log"
