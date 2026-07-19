> **Note — alternative topology, not the current setup.** provekit.online runs on a *dedicated* VPS via [DEPLOY_PROVEKIT_ONLINE.md](DEPLOY_PROVEKIT_ONLINE.md). Keep this only if you later co-host with another app on one box.

# Co-hosting ProveKit on the CereBroZen Contabo VPS

Run `provekit.online` on the **same VPS** that already serves `cerebrozen.in`. cere's Caddy
owns 80/443 and does auto-HTTPS, so ProveKit adds **no second gateway** — it runs its app
containers on cere's Docker network, and you add one site block to cere's Caddyfile. Caddy
then auto-provisions a Let's Encrypt cert for `provekit.online` (fixing the current bad-cert
error too).

```
                    ┌───────────── Contabo VPS (194.163.182.1) ─────────────┐
  DNS               │  cere's Caddy  :80/:443  (the only thing on 80/443)   │
  cerebrozen.in ───▶│    ├─ cerebrozen.in     → web:3000                    │
  provekit.online ─▶│    └─ provekit.online    → provekit-frontend:3000     │
                    │                            /api /v1 /healthz →         │
                    │                            provekit-backend:8000       │
                    │  + provekit-postgres, provekit-redis (internal)        │
                    └───────────────────────────────────────────────────────┘
```

## 1. DNS

Point `provekit.online` (and, if you want it, leave the reserved subdomains) at the VPS:

```
provekit.online.   A   194.163.182.1      # the same VPS IP as cerebrozen.in
```

Wait for it to resolve before reloading Caddy (Caddy needs DNS + open 80/443 to issue the cert).

## 2. Bring up ProveKit's containers (on the VPS)

```bash
git clone https://github.com/MobirizerServices/ProveKit && cd ProveKit
cp deploy/provekit.online.env.example deploy/provekit.online.env   # fill SECRET_KEY, SMTP pw…

# Confirm cere's network name (usually cerebrozen_default):
docker network ls | grep -i cere

# DB password (compose interpolates it into both postgres and DATABASE_URL):
export PROVEKIT_DB_PASSWORD='a-strong-db-password'
export CADDY_NETWORK='cerebrozen_default'      # from the command above

docker compose -f compose.contabo.yml up -d --build
```

This starts `provekit-postgres`, `provekit-redis`, `provekit-backend` (:8000), and
`provekit-frontend` (:3000) — **no host ports published**; cere's Caddy reaches them by
container name over the shared network. The backend runs migrations on boot.

## 3. Add ProveKit to cere's Caddy

Append this block to **`cere/deploy/Caddyfile`**:

```caddy
# ProveKit — agent observability (separate app, same Caddy)
provekit.online {
	import security_headers
	encode gzip zstd

	@api path /api/* /v1/* /healthz
	reverse_proxy @api provekit-backend:8000
	reverse_proxy provekit-frontend:3000
}
```

Reload cere's Caddy (zero downtime):

```bash
cd /path/to/cere
docker compose -f docker-compose.prod.yml exec caddy caddy reload --config /etc/caddy/Caddyfile
# (or: docker compose -f docker-compose.prod.yml up -d caddy)
```

Caddy now issues a Let's Encrypt cert for `provekit.online` automatically.

## 4. Validate

```bash
curl -sS https://provekit.online/ | grep -o "<title>[^<]*</title>"   # ProveKit login/landing
curl -sS https://provekit.online/api/auth/me                          # JSON (401/200), not HTML 404
curl -sS -o /dev/null -w "%{http_code}\n" https://provekit.online/healthz   # 200
```

Then in a browser: `https://provekit.online` loads with a **valid padlock**, sign up, create a
project, grab a key, and confirm a live trace from the SDK (`PROVEKIT_ENDPOINT=https://provekit.online`)
shows up in the portal.

## Notes

- **Isolation:** ProveKit uses its own Postgres/Redis containers — it does **not** touch cere's
  data. Only the Caddy network is shared.
- **Email:** the Titan SMTP password currently fails auth (535) — fix that in the BigRock/Titan
  panel and update `deploy/provekit.online.env`, or email won't send.
- **Updates:** `git pull && docker compose -f compose.contabo.yml up -d --build` (no Caddy
  reload needed unless the Caddyfile block changes).
- This replaces the home-router / external-nginx path (`compose.gateway.yml`) — that setup was
  fighting a consumer router. The Contabo + shared-Caddy path is the one cere already proves works.
