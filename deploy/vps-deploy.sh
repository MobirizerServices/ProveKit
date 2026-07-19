#!/usr/bin/env bash
# One-shot ProveKit deploy for a fresh dedicated VPS (Ubuntu/Debian), matching
# docs/DEPLOY_PROVEKIT_ONLINE.md. Idempotent — safe to re-run. Run as root on the box:
#
#   curl -fsSL https://raw.githubusercontent.com/MobirizerServices/ProveKit/main/deploy/vps-deploy.sh | bash
#
# Or clone first, then: bash deploy/vps-deploy.sh
set -euo pipefail
DOMAIN="${DOMAIN:-provekit.online}"
DIR="${DIR:-/root/ProveKit}"
ENV="deploy/provekit.online.env"

log(){ echo -e "\n\033[1;36m▶ $*\033[0m"; }

log "1/5 Docker"
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
docker compose version >/dev/null 2>&1 || { echo "docker compose plugin missing"; exit 1; }

log "2/5 Firewall (open 22/80/443)"
if command -v ufw >/dev/null; then ufw allow 22 >/dev/null; ufw allow 80 >/dev/null; ufw allow 443 >/dev/null; yes | ufw enable >/dev/null 2>&1 || true; fi

log "3/5 Code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone https://github.com/MobirizerServices/ProveKit "$DIR"; fi
cd "$DIR"

log "4/5 Secrets ($ENV)"
if [ ! -f "$ENV" ]; then
  SK=$(openssl rand -base64 48 | tr -d '\n')
  DBPW=$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9')
  cat > "$ENV" <<EOF
HOSTED=true
DOMAIN=$DOMAIN
SECRET_KEY=$SK
POSTGRES_PASSWORD=$DBPW
SUPERUSER_EMAILS=info@$DOMAIN
NEXT_PUBLIC_SITE_URL=https://$DOMAIN
MAX_BODY_BYTES=25000000
# Titan SMTP — fill the WORKING password to enable email (optional; not needed for login):
# SMTP_HOST=smtp.titan.email
# SMTP_PORT=587
# SMTP_STARTTLS=true
# SMTP_USER=info@$DOMAIN
# SMTP_PASSWORD=__reset_in_titan_panel__
# SMTP_FROM=Provekit <info@$DOMAIN>
EOF
  chmod 600 "$ENV"
  echo "  generated SECRET_KEY + POSTGRES_PASSWORD"
else
  echo "  $ENV already exists — leaving it as is"
fi

log "5/5 Launch (build + up)"
export DOMAIN
docker compose --env-file "$ENV" -f compose.prod.yml up -d --build

echo
echo "Waiting for the backend to become healthy…"
for i in $(seq 1 30); do
  if curl -fsS -m 3 http://localhost:8000/healthz >/dev/null 2>&1; then echo "  backend healthy ✓"; break; fi
  sleep 4
done

echo
echo "=============================================================="
echo " Done. Caddy is provisioning the TLS cert for $DOMAIN now."
echo " Watch it:   docker compose -f compose.prod.yml logs -f caddy"
echo " Then open:  https://$DOMAIN   (valid padlock once the cert issues)"
echo
echo " If anything failed, grab logs and paste them:"
echo "   docker compose -f compose.prod.yml ps"
echo "   docker compose -f compose.prod.yml logs --tail=60 caddy backend frontend"
echo "=============================================================="
