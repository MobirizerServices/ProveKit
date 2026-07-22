#!/usr/bin/env bash
# Install the ProveKit backup cron jobs. Run once on the VPS as root:
#
#   bash deploy/install-backups.sh
#
# Two jobs, because a backup nobody has restored is a belief, not a capability:
#   03:15 daily    deploy/backup.sh          pg_dump + gzip, 7-day retention
#   03:40 Sundays  deploy/verify-restore.sh  restore the newest dump into a throwaway db and
#                                            assert it is a working database, then drop it
#
# The drill is 25 minutes behind the dump so the two never contend for the same disk and CPU,
# and so a nightly dump that fails is still fresh enough to trip the drill's age check.
set -euo pipefail
DIR="${DIR:-/root/ProveKit}"
BACKUP_DIR="${BACKUP_DIR:-/root/provekit-backups}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"

BACKUP_LINE="15 3 * * * BACKUP_DIR=$BACKUP_DIR RETAIN_DAYS=$RETAIN_DAYS bash $DIR/deploy/backup.sh >> /var/log/provekit-backup.log 2>&1"
DRILL_LINE="40 3 * * 0 BACKUP_DIR=$BACKUP_DIR bash $DIR/deploy/verify-restore.sh >> /var/log/provekit-restore-drill.log 2>&1"

# Replace any existing ProveKit backup/drill cron lines, then add ours. `|| true` so an empty
# crontab (grep finds nothing → exit 1) doesn't abort under `set -e`.
( crontab -l 2>/dev/null | grep -v -e 'deploy/backup.sh' -e 'deploy/verify-restore.sh' || true
  echo "$BACKUP_LINE"
  echo "$DRILL_LINE" ) | crontab -

echo "installed cron:"
crontab -l | grep -e backup.sh -e verify-restore.sh
echo "logs: /var/log/provekit-backup.log  /var/log/provekit-restore-drill.log"
echo "drill verdict: $BACKUP_DIR/last-drill.txt (stops updating if the cron dies — alert on its age)"
echo
echo "Run the drill once now, before you trust any of this:"
echo "  BACKUP_DIR=$BACKUP_DIR bash $DIR/deploy/backup.sh && BACKUP_DIR=$BACKUP_DIR bash $DIR/deploy/verify-restore.sh"
