# Deploying ProveKit

Two ways to run it: **local** (single user, zero config) and **hosted** (multi-user,
behind TLS).

## Local (single user)

```bash
# backend — SQLite, no login
cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn provekit.main:app --port 8100

# frontend
cd frontend && npm install && npm run dev   # http://localhost:3001
```

No `SECRET_KEY` needed — a key file is generated next to the SQLite db to sign sessions.
`HOSTED` is off, so there's no login wall; you land in a default project.

Point an agent at it: set `PROVEKIT_ENDPOINT=http://localhost:8100` and a project key, add
`@pk.trace`, and runs show up under **Traces**.

## Hosted (multi-user, TLS)

Prerequisites: a VM with Docker, a domain pointed at it (A record), ports 80/443 open.

```bash
export DOMAIN=provekit.example.com
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
export POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
export SENTRY_DSN=...               # optional error reporting

docker compose -f compose.prod.yml up -d --build
```

Caddy auto-provisions a Let's Encrypt certificate for `$DOMAIN`. Open `https://$DOMAIN` — in
hosted mode you'll be asked to sign up. Your users then set
`PROVEKIT_ENDPOINT=https://$DOMAIN` and a project key.

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
- Scaling: add backend replicas behind Caddy for horizontal scale.
- Migrations run automatically on startup; to run manually:
  `docker compose -f compose.prod.yml exec backend alembic upgrade head`.
