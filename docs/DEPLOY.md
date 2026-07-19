# Deploying ProveKit

Two ways to run it: **local** (single user, zero config) and **hosted** (multi-user,
behind TLS).

> **Deploying to production?** The live site (provekit.online) runs the dedicated-VPS path —
> follow **[DEPLOY_PROVEKIT_ONLINE.md](DEPLOY_PROVEKIT_ONLINE.md)** for the exact runbook, plus
> `deploy/vps-deploy.sh` (one-shot), `deploy/backup.sh` (daily backups), and `deploy/harden.sh`
> (security). The sections below are the general reference.

## Local (single user)

```bash
# backend — SQLite, no login
cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn provekit.main:app --port 8000

# frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

No `SECRET_KEY` needed — a key file is generated next to the SQLite db to sign sessions.
`HOSTED` is off, so there's no login wall; you land in a default project.

Point an agent at it: set `PROVEKIT_ENDPOINT=http://localhost:8000` and a project key, add
`import provekit.auto`, and runs show up under **Traces**.

## Hosted on a VPS (multi-user, TLS) — step by step

The `compose.prod.yml` stack (Caddy TLS → frontend + backend, Postgres, Redis) is verified to
boot and serve the full flow against Postgres. A ~$5/mo VPS is plenty to start.

**1. Provision + point DNS.** Create a small Linux VM (DigitalOcean, Hetzner, …), open ports
80 and 443, and add a DNS **A record** for your domain → the VM's IP.

**2. Install Docker** on the VM:

```bash
curl -fsSL https://get.docker.com | sh
```

**3. Get the code** and set secrets (generate fresh — never reuse):

```bash
git clone https://github.com/MobirizerServices/ProveKit && cd ProveKit
export DOMAIN=provekit.example.com
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
export POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
# optional: SENTRY_DSN, and SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_FROM to send reset emails
```

**4. Bring it up:**

```bash
docker compose -f compose.prod.yml up -d --build
```

Caddy auto-provisions a Let's Encrypt certificate for `$DOMAIN` (this needs the DNS record
from step 1 to already resolve). Open `https://$DOMAIN` — you'll be asked to sign up. Your
users then set `PROVEKIT_ENDPOINT=https://$DOMAIN` and a project key, and add `@pk.trace`.

**5. Verify:** `curl https://$DOMAIN/healthz` → `{"ok":true,...}`.

> Put the `export` lines in a `.env` file next to `compose.prod.yml` instead of the shell so
> they survive reboots (compose reads it automatically). Never commit it.

### What hosted mode changes

- `HOSTED=true`: strict SSRF guard on the outbound emit path (blocks private/internal IPs,
  resolves DNS), auth required (no default local user), secure session cookies.
- Postgres (schema managed by Alembic migrations on startup). Redis is optional.
- Same-origin: the browser only talks to `https://$DOMAIN`; Caddy routes `/api` and `/v1` to
  the backend, everything else to the frontend. No CORS, first-party cookies.
- `SECRET_KEY` is required — it signs sessions and derives the local key material. Losing it
  just logs everyone out (they sign back in); no stored user secrets are lost.
- **Email verification needs SMTP** — until you configure a mail provider, verification/reset
  messages aren't sent (signup still works).

### Operations

- Health: `GET /healthz` — wired into the compose healthcheck.
- Logs: JSON lines in hosted mode, each carrying `request_id` (also the `X-Request-ID`
  response header). Traced inputs/outputs are never logged by the server.
- Scaling: add backend replicas behind Caddy for horizontal scale. Redis (in the stack)
  keeps rate-limit windows global across the workers.
- **Backups:** use `deploy/backup.sh` (daily `pg_dump` + gzip, 7-day retention) and install the
  cron with `deploy/install-backups.sh`. Ship the dumps off-box for real durability.
- **Hardening:** `deploy/harden.sh` applies security updates, enables unattended-upgrades,
  installs fail2ban, and confirms the firewall.
- Migrations run automatically on startup; to run manually:
  `docker compose -f compose.prod.yml exec backend alembic upgrade head`.
- Tunables (env): `INGEST_RATE_PER_MIN` (default 600), `RUNS_RETENTION` (default 10000 spans
  per project).
