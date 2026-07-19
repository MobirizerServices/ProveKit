# Deploying to provekit.online

This matches the live gateway contract (`provekit.online.conf`): an external **nginx** on a
separate box terminates TLS and proxies to the app box `192.168.1.2`:

```
https://provekit.online/        → 192.168.1.2:3000   (frontend)
https://provekit.online/api/*   → 192.168.1.2:8000   (backend)
http → https (301);  admin/api/mcp subdomains → 404 (not wired yet)
```

Only `/api/*` goes to the backend. **`/v1/*` (the SDK trace-ingest endpoint) and `/healthz`
go to the frontend**, which forwards them to the backend via the Next rewrite
(`API_PROXY_TARGET`). So the app is deployed with the frontend on **3000** and the backend on
**8000**, both bound `0.0.0.0`, and `compose.gateway.yml` wires the internal forwarding.

> If Pawan later routes `/v1/*` + `/healthz` straight to `:8000` (or dedicates
> `api.provekit.online → :8000`), the double-hop disappears and ingest hits the backend
> directly — no app change needed, it just gets one hop faster.

## 1. Configure

```bash
cp deploy/provekit.online.env.example deploy/provekit.online.env   # gitignored
# then edit deploy/provekit.online.env:
#   SECRET_KEY   = python -c "import secrets;print(secrets.token_urlsafe(48))"
#   DATABASE_URL = postgres password must match POSTGRES_PASSWORD in compose.gateway.yml
#   SMTP_PASSWORD= from the BigRock/Titan panel  (info@provekit.online)
```

Set the same DB password in `compose.gateway.yml` (`POSTGRES_PASSWORD`) and in
`DATABASE_URL` inside the env file.

## 2. Bring it up (on 192.168.1.2)

```bash
docker compose -f compose.gateway.yml up -d --build
```

This starts Postgres, Redis, the backend (`:8000`), and the frontend (`:3000`), all published
on `0.0.0.0` so the LAN nginx can reach them. The backend runs its migrations on boot.

## 3. Validate

On the box:

```bash
curl -s http://localhost:3000/ | head              # frontend responds
curl -s http://localhost:8000/api/auth/me          # backend responds under /api
curl -s http://localhost:8000/healthz              # {"ok":true,...}
lsof -i :3000 -i :8000                              # both bound *:3000 / *:8000 (not 127.0.0.1)
```

Externally (phone on mobile data):

```bash
curl -s https://provekit.online/ | head                     # valid padlock, frontend
curl -s https://provekit.online/api/auth/me                 # backend via /api
# SDK ingest reaches the backend through the frontend rewrite:
curl -s -o /dev/null -w "%{http_code}\n" https://provekit.online/healthz    # 200
```

## 4. Point an agent at it

```bash
pip install "provekit[trace]"
export PROVEKIT_ENDPOINT=https://provekit.online     # SDK posts to /v1/traces
export PROVEKIT_API_KEY=pk_...                        # created in the portal
python -c "import provekit.auto; ..."                # run your agent
```

The SDK's `POST https://provekit.online/v1/traces` → nginx `location /` → frontend:3000 →
Next rewrite → backend:8000. Verify the run appears in the portal Traces view.

## 5. Email

`info@provekit.online` (Titan via BigRock). Use **port 587 + STARTTLS** — the mailer uses
STARTTLS, not implicit-SSL 465. Config lives in `deploy/provekit.online.env` (secret, never
committed). **DKIM/SPF are pending on Pawan's side**, so until those DNS records exist mail
will land in spam — re-test deliverability after they go live.

## 6. Notes

- `HOSTED=true` is set for both services: the backend requires login, and the frontend
  middleware redirects portal routes to `/login` without a session.
- `SUPERUSER_EMAILS=info@provekit.online` bootstraps the `/admin` console for that account.
- `MAX_BODY_BYTES=25000000` (nginx allows 50 MB) covers large trace batches.
- Gateway-layer failures (SSL, subdomain 404s, 502 with the service up) → Pawan. App-layer
  issues are ours.
