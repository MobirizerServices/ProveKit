# One-click deploy

Stand up a working ProveKit instance on a managed platform without touching a VM. Three
targets ship with config in the repo:

| Platform | File | What the button does |
|---|---|---|
| Render | [`render.yaml`](../render.yaml) | Blueprint: Postgres + backend + frontend, all three |
| Railway | [`railway.json`](../railway.json) | Backend service; the frontend and Postgres are added alongside it |
| Fly.io | [`fly.toml`](../fly.toml) | Backend app; `flyctl` drives it, there is no hosted button |

> **Untested against real accounts.** These files were written from the Dockerfiles, the
> compose stacks and `backend/provekit/config.py`, and the start commands were checked by
> running them locally. Nobody has deployed them to a paid Render / Railway / Fly account,
> so treat the first deploy as a smoke test and read [Verify](#verify) before you trust it.
> For a path that *is* verified end to end, use [DEPLOY_PROVEKIT_ONLINE.md](../docs/DEPLOY_PROVEKIT_ONLINE.md).

## The shape all three deploy

Two services and a database. The **frontend is the only public entry point**: the browser
loads it, and the Next server rewrites `/api`, `/v1` and `/healthz` to the backend
(`frontend/next.config.js`).

```
 browser ──▶ frontend (Next)  ──▶ backend (FastAPI) ──▶ Postgres
 SDK     ──▶ /v1/traces ───────┘
```

That layout is not an aesthetic choice. The session cookie is set `SameSite=Lax`
(`backend/provekit/routers/auth.py`), so if you split the browser across two origins —
frontend on one domain, backend on another via `NEXT_PUBLIC_API_BASE` — the cookie is never
sent and every authed request 401s while the pages themselves look fine. Proxying keeps
everything first-party and means no CORS at all.

The consequence: **the frontend has to know the backend's address at build time.** With
`output: "standalone"`, Next bakes the rewrite destination into `routes-manifest.json`, so
`API_PROXY_TARGET` is a Docker *build argument* (`frontend/Dockerfile`), not a runtime
variable. Changing it requires a rebuild, not a restart.

## The three variables that decide whether it boots

Everything else in `config.py` has a working default. These do not:

| Variable | Service | Why it matters |
|---|---|---|
| `SECRET_KEY` | backend | Signs sessions and derives the key material that seals provider credentials. `HOSTED=true` **refuses to boot** on an empty, weak or under-16-character value (`_guard_production_config` in `backend/provekit/main.py`). Generate it, never reuse one. |
| `DATABASE_URL` | backend | Must use the **`postgresql+psycopg://`** scheme. All three platforms hand out `postgres://` or `postgresql://`, which SQLAlchemy resolves to the psycopg2 driver — and the image ships psycopg 3 only (`backend/requirements.txt`). A plain paste dies on the first connect with `No module named 'psycopg2'`. Each config file wraps the start command with a `sed` that rewrites the scheme; it is a no-op if the URL is already correct. |
| `API_PROXY_TARGET` | frontend (build arg) | Where the Next server forwards `/api` and `/v1`. Wrong value → the portal renders and every request 502s. |

Two more worth setting once the URLs exist:

- `HOSTED=true` on **both** services — the login wall is enforced in two places, the backend
  (auth required, secure cookies, strict SSRF guard) and `frontend/middleware.ts` (portal
  routes redirect to `/login`). Setting it on only one leaves a confusing half-open portal.
- `WEB_BASE_URL` on the backend — the base for links in verification and password-reset
  email. It has to be the *frontend's* public URL, which does not exist until the platform
  has created the service, so it is a genuine second pass. Wrong value = working signup with
  dead links in the mail.

## Render

The only target where a single file creates all three resources.

```markdown
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/MobirizerServices/ProveKit)
```

Render reads `render.yaml` from the repo root and provisions `provekit-db`,
`provekit-backend` and `provekit-frontend`. `SECRET_KEY` uses `generateValue: true`, so it
is created for you and never appears in the repo; `DATABASE_URL` is wired from the database
with `fromDatabase`.

**Manual steps that cannot be automated:**

1. **`WEB_BASE_URL`.** It is declared `sync: false`, so Render leaves it blank. After the
   blueprint finishes, copy the frontend's URL (`https://provekit-frontend-xxxx.onrender.com`)
   into the backend service's environment and let it redeploy. Blueprints have no way to
   reference another service's *full URL* — only its host — and the app needs the scheme.
2. **Check the backend's internal address.** `render.yaml` sets
   `API_PROXY_TARGET=http://provekit-backend:8000`, which assumes Render's internal address
   for that service is its name. Open the backend service → **Connect** → Internal Address.
   If it differs (a name collision in your workspace will change it), fix
   `API_PROXY_TARGET` on the frontend service and **redeploy the frontend** — a restart is
   not enough, the value is baked at build time.
3. **Redis, if you open the instance to other people.** Not in the blueprint, because it is
   optional and an extra paid resource. Without it, rate-limit windows and the per-account
   quota counters are per-worker and reset on restart — `GET /api/projects/usage` reports
   `approximate: true` and the portal repeats it. Add a Render Key Value instance and set
   `REDIS_URL` on the backend. See the quota table in [DEPLOY.md](../docs/DEPLOY.md).

**Known unknown:** `API_PROXY_TARGET` is declared as an environment variable, and the
frontend Dockerfile consumes it as `ARG`. This relies on Render exposing service
environment variables to the Docker build as build arguments. If the frontend comes up
proxying to the Dockerfile default (`http://backend:8000`) and every `/api` call 502s, that
assumption was wrong: set the build argument in the service's settings instead, or rename
the backend service to `backend` so the default resolves.

**Free plan caveats.** Free web services sleep after idling, so the first trace ingested
after a quiet period pays a cold start, and free Postgres is time-limited by Render. Check
Render's current pricing before pointing production agents at it.

## Railway

Railway's button needs a *published template*, which is created in Railway's dashboard from
your fork — there is no repo file that produces one. Once published, the markdown is:

```markdown
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/YOUR-TEMPLATE-CODE)
```

Until then, "New Project → Deploy from GitHub repo" gets you the same instance in about the
same number of clicks. Either way you end up creating three things:

1. **Postgres** — "New → Database → Add PostgreSQL". Railway injects `DATABASE_URL` into
   services you reference it from.
2. **Backend service** — from this repo, with **Root Directory `backend`**. That makes the
   Docker build context `backend/`, which is what `backend/Dockerfile` expects (it does
   `COPY requirements.txt .`). `railway.json` at the repo root supplies the builder, the
   start command with the psycopg scheme fix, and the `/healthz` check. If Railway does not
   pick up the root config once the root directory is set, copy it in:
   `cp railway.json backend/railway.json`.
   Variables: `SECRET_KEY` (generate it), `HOSTED=true`,
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`, and `WEB_BASE_URL` once the frontend has a
   domain.
3. **Frontend service** — same repo, **Root Directory `frontend`**, Dockerfile builder.
   Variables: `HOSTED=true` and `API_PROXY_TARGET=http://backend.railway.internal:8000`,
   substituting whatever you named the backend service. Railway's private network resolves
   `<service>.railway.internal`. Generate a public domain for this service only.

Generate the secret with the same one-liner the VPS runbook uses:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Known unknowns:** whether Railway reads a repo-root `railway.json` for a service whose
root directory is a subdirectory, and whether it forwards service variables to the Docker
build as build arguments (the frontend needs `API_PROXY_TARGET` at build time). Both have
the same symptom — a frontend that renders but 502s on `/api` — and the same fix: set the
value as an explicit build argument in the service's build settings and redeploy.

## Fly.io

Fly has no hosted deploy button; the flow is `flyctl` from a clone. `fly.toml` in the repo
root is the **backend** app.

```bash
git clone https://github.com/MobirizerServices/ProveKit && cd ProveKit

# 1. Postgres, attached to the backend app (this sets DATABASE_URL as a secret).
fly apps create provekit-backend
fly postgres create --name provekit-db
fly postgres attach provekit-db --app provekit-backend

# 2. The one secret that must not be generated by anything but you.
fly secrets set --app provekit-backend \
  SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

# 3. Deploy. The path argument is the build context — backend/Dockerfile copies
#    requirements.txt from its own directory, so the repo root will not build.
fly deploy ./backend --config fly.toml
```

Then the frontend, as a second app. Save this as `frontend/fly.toml` (it is not in the repo
because a Fly config is per-app and the root file is taken):

```toml
app = "provekit-frontend"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"
  [build.args]
    # Baked into the standalone Next build. The public backend URL, not the .internal one —
    # see the note below.
    API_PROXY_TARGET = "https://provekit-backend.fly.dev"

[env]
  HOSTED = "true"
  PORT = "3000"

[http_service]
  internal_port = 3000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

```bash
fly deploy ./frontend --config frontend/fly.toml
fly secrets set --app provekit-backend WEB_BASE_URL=https://provekit-frontend.fly.dev
```

**Why the public backend URL and not `provekit-backend.internal`.** Both work, but
`.internal` is plain 6PN DNS — it bypasses fly-proxy, and a machine stopped by
`auto_stop_machines` will not be woken by a request to it. With `min_machines_running = 0`
on the backend that is an outage on the first request after an idle period. Going through
`https://provekit-backend.fly.dev` lets fly-proxy start the machine. The browser still only
ever sees the frontend origin, so cookies stay first-party either way. If you prefer the
private address, set `min_machines_running = 1` and `auto_stop_machines = "off"` on the
backend and use `http://provekit-backend.internal:8000`.

**Known unknowns:** Fly has been moving from unmanaged `fly postgres` to Managed Postgres
(`fly mpg`), so the create/attach commands above may have shifted; what matters is that the
attach step ends with `DATABASE_URL` set as a secret on the backend app. `fly.toml` also
assumes app names `provekit-backend` / `provekit-frontend` are free — Fly app names are
global, so if they are taken, rename in both configs *and* in `API_PROXY_TARGET`.

## Verify

Same checks on every platform. Run them in order; each one fails differently.

```bash
# 1. Backend is alive and migrated. Alembic runs in the lifespan before the app serves
#    traffic, so any response at all means the schema applied; ok:true adds that the
#    connection is live (and Redis, if you configured it).
curl https://<frontend-url>/healthz

# 2. The proxy hop is real: this is served by the backend through the Next server.
curl -i https://<frontend-url>/api/projects        # expect 401, not 502
```

Then in a browser: open the frontend URL, sign up (you get the first account), create a
project, copy its key. Point an agent at it —

```bash
PROVEKIT_ENDPOINT=https://<frontend-url>
PROVEKIT_API_KEY=pk_...
```

— add `import provekit.auto`, run it, and confirm the run appears under **Traces**. A trace
that lands is the only proof that ingest, the database and the proxy all work together.

Failure modes worth recognising:

- **Backend crash-loops at boot, no logs past startup** — `SECRET_KEY` is missing or under
  16 characters, and `HOSTED=true` refuses to start. This is deliberate.
- **`No module named 'psycopg2'`** — the `DATABASE_URL` scheme rewrite did not run. Check
  the platform actually used the start command from the config file, or set `DATABASE_URL`
  by hand with `postgresql+psycopg://`.
- **Portal loads, every request 502s** — `API_PROXY_TARGET` is wrong or was not applied at
  build time. Rebuild the frontend, do not just restart it.
- **Signup works, reset emails have dead links** — `WEB_BASE_URL` still points somewhere
  else. (No SMTP configured at all means the links are only logged, never sent; see
  [DEPLOY.md](../docs/DEPLOY.md).)

## Before anyone else signs up

These platforms make it trivial to hand out the URL, which changes the threat model. Two
things are off by default and worth turning on:

- **Per-account quotas.** `MONTHLY_SPAN_QUOTA` and `MAX_PROJECTS_PER_ACCOUNT` both default
  to `0` (unlimited) so that a single-tenant install never starts refusing its owner's data.
  Rate limits bound bursts, not totals. The table in [DEPLOY.md](../docs/DEPLOY.md) has the
  effects.
- **`REDIS_URL`.** Without it the quota counters are per-worker and reset on restart — a
  deterrent, not a ceiling.

Also note that the ingest spool (`services/spool.py`) stages accepted batches to a temp
directory by default. On these platforms the filesystem is ephemeral, so a machine replaced
mid-outage loses whatever was staged but not yet committed. Set `SPOOL_DIR` to a mounted
volume if that matters to you.
