#!/usr/bin/env bash
# Toggle which app owns the Contabo VPS (ports 80/443). Runs ONE at a time — stopping the
# other and starting the requested one. Data survives switching (named volumes persist; we
# never pass -v). Each app runs its own Caddy, so only the active one holds 80/443.
#
#   ./switch.sh provekit    # stop cere, start ProveKit (serves provekit.online)
#   ./switch.sh cere        # stop ProveKit, start cere   (serves cerebrozen.in)
#   ./switch.sh status      # what's running now
#   ./switch.sh down        # stop both (nothing served)
#
# Override paths if the repos live elsewhere:
#   CERE_DIR=/srv/cere PROVEKIT_DIR=/srv/ProveKit ./switch.sh provekit
set -euo pipefail

CERE_DIR="${CERE_DIR:-$HOME/cere}"
PROVEKIT_DIR="${PROVEKIT_DIR:-$HOME/ProveKit}"
CERE=(docker compose -f docker-compose.prod.yml --env-file .env.production)
PK=(docker compose -f compose.prod.yml --env-file deploy/provekit.online.env)

cere_down() { echo "→ stopping cere…";     ( cd "$CERE_DIR"     && "${CERE[@]}" down ) || true; }
pk_down()   { echo "→ stopping ProveKit…"; ( cd "$PROVEKIT_DIR" && "${PK[@]}"   down ) || true; }
cere_up()   { echo "→ starting cere…";     ( cd "$CERE_DIR"     && "${CERE[@]}" up -d --build ); }
pk_up()     { echo "→ starting ProveKit…"; ( cd "$PROVEKIT_DIR" && "${PK[@]}"   up -d --build ); }

case "${1:-}" in
  provekit) pk_down; cere_down; pk_up;   echo "✓ provekit.online is now live" ;;
  cere)     pk_down; cere_down; cere_up; echo "✓ cerebrozen.in is now live" ;;
  down)     pk_down; cere_down;          echo "✓ both stopped" ;;
  status)   docker ps --format '{{.Names}}\t{{.Status}}' | grep -Ei 'caddy|provekit|cere|web|platform|engine|admin|app' || echo "(nothing running)" ;;
  *) echo "usage: $(basename "$0") {provekit|cere|status|down}"; exit 1 ;;
esac
