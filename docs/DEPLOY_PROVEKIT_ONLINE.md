# Deploying provekit.online (dedicated Contabo VPS)

ProveKit runs on its **own** VPS — self-contained, exactly like CereBroZen runs on its. A
Caddy container owns ports 80/443 and auto-provisions a Let's Encrypt cert for
`provekit.online`; every other service (frontend, backend, Postgres, Redis) is internal to the
compose network. This is `compose.prod.yml` + `Caddyfile`.

```
DNS: provekit.online ──▶ <your VPS IP>
     ┌──────────── VPS ────────────┐
     │ caddy  :80/:443 (auto-TLS)   │
     │   ├─ /api /v1 /healthz → backend:8000
     │   └─ everything else   → frontend:3000
     │ + postgres, redis (internal) │
     └──────────────────────────────┘
```

## 1. DNS

Point the domain (and drop `www` unless you have a record) at the new VPS:

```
provekit.online.   A   <VPS_IP>
```

Caddy needs this resolving + ports 80/443 open before it can issue the cert.

## 2. Secrets

```bash
git clone https://github.com/MobirizerServices/ProveKit && cd ProveKit
cp deploy/provekit.online.env.example deploy/provekit.online.env   # gitignored
# Fill in: SECRET_KEY, POSTGRES_PASSWORD, and the WORKING Titan SMTP password.
# DOMAIN=provekit.online is already set.
```

## 3. Bring it up

```bash
docker compose --env-file deploy/provekit.online.env -f compose.prod.yml up -d --build
```

That starts Postgres, Redis, the backend (`:8000`, internal), the frontend (`:3000`, internal),
and Caddy (`:80/:443`, public). The backend runs migrations on boot; Caddy issues the TLS cert
automatically. `HOSTED=true` is set, so the portal requires login and the middleware gate is on.

## 4. Validate

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://provekit.online/          # 200/307, valid padlock
curl -sS https://provekit.online/api/auth/me                                # JSON (401/200), not HTML
curl -sS -o /dev/null -w "%{http_code}\n" https://provekit.online/healthz   # 200
```

Then in a browser: sign up → create a project → grab a key → run an agent with
`PROVEKIT_ENDPOINT=https://provekit.online` and confirm the trace shows in the portal.

## 5. Point an agent at it

```bash
pip install "provekit[trace]"
export PROVEKIT_ENDPOINT=https://provekit.online
export PROVEKIT_API_KEY=pk_...          # from the portal
python -c "import provekit.auto; ..."   # your agent
```

Caddy routes `/v1/traces` straight to the backend, so ingest is a direct path (no proxy hops).

## Updates

```bash
git pull && docker compose --env-file deploy/provekit.online.env -f compose.prod.yml up -d --build
docker image prune -f
```

## Notes

- **Own VPS = simplest.** Ignore `compose.gateway.yml` (external-nginx / home-box) and
  `compose.contabo.yml` + `deploy/switch.sh` (co-hosting on cere's VPS) — those were for other
  topologies. On a dedicated box, `compose.prod.yml` is all you need.
- **Superadmin:** `SUPERUSER_EMAILS=info@provekit.online` bootstraps the `/admin` console.
- **Email:** the Titan SMTP password currently fails auth (535) — fix it in the BigRock/Titan
  panel and update the env, or password-reset / verification mail won't send. Also add SPF/DKIM
  DNS records or mail lands in spam.
