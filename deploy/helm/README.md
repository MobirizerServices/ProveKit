# ProveKit on Kubernetes

Two ways to install, same topology as the compose stack:

- **Helm** — `deploy/helm/provekit`. Templated, with the bundled Postgres and Redis
  switchable off in favour of managed services.
- **Plain manifests** — [`deploy/k8s`](../k8s) for people who don't run Helm.
  `kubectl apply -k deploy/k8s`.

The shape is the same either way, and it matches `compose.prod.yml`: an ingress terminates
TLS on one hostname and routes `/api`, `/v1` and `/healthz` to the backend and everything
else to the frontend. One origin means session cookies stay first-party, there's no CORS,
and the SDK posts OTLP to `https://<host>/v1/traces`.

```
             ingress (TLS, one host)
                │
    /api /v1 /healthz          everything else
                │                    │
          backend :8000         frontend :3000
                │
     Postgres :5432   Redis :6379
```

Ports are the container ports the images actually listen on — 8000 and 3000, set by
`backend/Dockerfile` and `frontend/Dockerfile`. The 8100/3001 in `docker-compose.yml` are
host publishes for local Docker, not something the images know about.

## Images

**ProveKit publishes no public container images.** Build and push your own first:

```bash
docker build -t <registry>/provekit-backend:0.1.0 backend/
docker build -t <registry>/provekit-frontend:0.1.0 \
  --build-arg API_PROXY_TARGET=http://backend:8000 frontend/
docker push <registry>/provekit-backend:0.1.0
docker push <registry>/provekit-frontend:0.1.0
```

`API_PROXY_TARGET` is a **build argument**, not runtime config: `output: "standalone"` fixes
the Next rewrite destination at build time. The ingress sends `/api` and `/v1` straight to the
backend, so the rewrite only catches calls that reach the Next server itself — but when it
does fire it must point somewhere real. Either bake the in-cluster Service DNS name into the
image, or set `backend.service.name=backend` so the stock default (`http://backend:8000`)
resolves. The second option drops the release prefix from the Service name, so it only works
with one release per namespace.

Then point the chart at your registry with `imageRegistry` (prefix for both ProveKit images)
or `backend.image.repository` / `frontend.image.repository` (full paths). `imageRegistry` is
not applied to the Postgres and Redis images — set those repositories directly if you mirror
Docker Hub.

## Install

```bash
helm install provekit deploy/helm/provekit \
  --namespace provekit --create-namespace \
  --set imageRegistry=<registry> \
  --set config.domain=provekit.example.com \
  --set ingress.enabled=true \
  --set secrets.secretKey="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --set postgresql.auth.password="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
```

Verify: `curl https://provekit.example.com/healthz` → `{"ok":true,...}`. Then sign up in the
portal, create a project, and point an agent at it with `PROVEKIT_ENDPOINT` + a project key.

Without an ingress (a kind or minikube kick-of-the-tyres), leave `ingress.enabled=false` and
port-forward — `helm install` prints the commands.

No migration Job and no init container: `alembic upgrade head` runs in the backend's startup
lifespan and takes a Postgres advisory lock first, so concurrent replicas serialize instead of
racing. The `startupProbe` allows 150s for a replica that has to wait its turn.

## The values that matter

| Value | Default | Why you care |
|---|---|---|
| `secrets.secretKey` | *(empty)* | **Required.** Signs sessions and derives the key material that seals provider credentials at rest. `config.hosted=true` refuses to boot with fewer than 16 chars or a known dev default, and the chart fails at template time rather than in a CrashLoopBackOff. Rotating it logs everyone out; it loses no stored data. |
| `secrets.databaseUrl` | *(empty → bundled Postgres)* | `postgresql+psycopg://user:pass@host:5432/provekit`. Set it and `postgresql.enabled=false` to use a managed database. The password is interpolated into a URL — percent-encode it, or keep it URL-safe. |
| `config.hosted` | `true` | Login wall, secure cookies, strict SSRF guard on the outbound emit path, JSON logs, and the frontend's middleware login gate. Turn it off only for a single-user install on a trusted network. |
| `config.domain` | *(empty)* | The public hostname. Drives `CORS_ORIGINS`, `WEB_BASE_URL`, `NEXT_PUBLIC_SITE_URL` and the ingress host. Required when `ingress.enabled=true`. |
| `secrets.redisUrl` / `redis.enabled` | *(bundled Redis)* | Rate-limit windows, playground spend counters and monthly span quotas live in Redis. Without it they are per-worker and reset on restart — `/api/projects/usage` reports `approximate: true` and the portal repeats it. Set this before you open an instance to other people. |
| `spool.persistence.enabled` | `false` | See below. |
| `backend.replicaCount` / `backend.workers` | `2` / `1` | Replicas for horizontal scale, uvicorn workers to fill a large pod. Either way the limiter windows are only global with Redis. |
| `config.ingestRatePerMin` | `600` | Ingest requests per project per minute. |
| `config.runsRetention` | `10000` | Spans kept per project; older ones are pruned. |
| `config.maxBodyBytes` | `25000000` | Rejects larger request bodies with 413. Your ingress needs a matching limit — see the `proxy-body-size` annotation in `values.yaml`. |
| `config.monthlySpanQuota`, `config.maxProjectsPerAccount` | `0` (unlimited) | Per-account ceilings. Rate limits bound bursts, not totals; set both if anyone can sign up. |
| `config.superuserEmails` | *(empty)* | Bootstraps the `/admin` console for those accounts. |
| `config.smtp.*` + `secrets.smtpPassword` | *(empty)* | Without `SMTP_HOST`, password-reset and verification links are logged instead of sent. Signup still works. |
| `config.redactPii` | `false` | Masks emails, cards, SSNs, phones and common secret keys in captured span input/output before storage. |

### Spool settings

`services/spool.py` fsyncs every ingest batch to disk *before* the request is acknowledged and
releases it once the rows commit, so a database blip cannot destroy data the exporter believes
was accepted. A drain task replays whatever is left staged. Its depth also drives ingest
backpressure and the `ingest` block in `/healthz`.

| Value | Default | Effect |
|---|---|---|
| `spool.enabled` | `true` | Turning it off makes ingest a straight write-through. Don't. |
| `spool.dir` | `/data/spool` | Where batches are staged. The chart mounts a volume here; `/data` exists in the image and is owned by uid 10001. |
| `spool.maxDepth` | `5000` | Refuse new batches with a retriable 503 once this many are waiting to land, so a spike becomes backpressure instead of unbounded disk and database pressure. 0 disables it. |
| `spool.drainSeconds` | `5.0` | How often the background drainer retries staged batches. |
| `spool.persistence.enabled` | `false` | `false` uses an emptyDir: staged batches survive a container crash, not a pod being rescheduled. `true` uses a PVC — but the spool is node-local by design, and one ReadWriteOnce claim shared by a Deployment pins every replica to one node. Use a ReadWriteMany class, or `backend.replicaCount: 1`. |

Watch `/healthz` for it: `queue_depth` is accepted-but-unlanded batches and `lag_seconds` the
age of the oldest. Both are 0 on a healthy instance; a lag that keeps climbing means the
database is behind, which is otherwise invisible until someone notices missing traces.

### Health checks

`/healthz` is wired as `startupProbe`, `readinessProbe` and `livenessProbe` on the backend. It
returns 503 when the database — or a configured Redis — is unreachable, so readiness pulls the
pod out of the Service during an outage. Liveness uses the same endpoint with
`failureThreshold: 12` (about four minutes at a 20s period): a database blip should drain
traffic, not restart-loop the whole fleet while the database recovers. Raise it further if
your database has longer maintenance windows.

The frontend probes `/` — the landing page, which needs no session even with `HOSTED=true`.

## Secrets

By default the chart renders a Secret containing `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` and
optionally `SENTRY_DSN` / `SMTP_PASSWORD`. `--set` puts those values in the Helm release
secret too; use `-f my-values.yaml` with a file you keep out of git, or hand the chart a Secret
you manage elsewhere:

```yaml
secrets:
  existingSecret: provekit-secrets   # SealedSecret, External Secrets Operator, …
```

It is consumed with `envFrom`, so any extra keys in it become extra env vars — which is how you
add anything `config.extra` doesn't cover.

Only the backend mounts it. The frontend gets explicit env vars (`HOSTED`, `PORT`,
`NEXT_PUBLIC_SITE_URL`), so the database URL and `SECRET_KEY` never reach the portal pods.

## Postgres and Redis

Both are rendered by this chart rather than pulled in as subcharts, so `helm install` works
with no chart repositories configured and no network beyond the image pulls.

The bundled Postgres is one StatefulSet with one PVC: no replication, no failover, **no
backups**. It exists so a fresh install comes up working. Before it holds anything you would
miss, move to a managed database:

```yaml
postgresql:
  enabled: false
secrets:
  databaseUrl: "postgresql+psycopg://provekit:…@db.internal:5432/provekit"
```

The bundled Redis is deliberately ephemeral — it holds counters, not records.

## Upgrading

```bash
helm upgrade provekit deploy/helm/provekit -f my-values.yaml
```

Config and secret changes roll the backend pods (the Deployment carries checksum annotations;
`envFrom` alone would not restart anything). Migrations run on the new pods as they start.
`maxUnavailable: 0` keeps the old replicas serving until the new ones pass readiness.

## Validating a change

`config.hosted=true` refuses a weak `SECRET_KEY`, so a bare `helm lint` fails by design.
`ci/lint-values.yaml` carries throwaway values for exactly that (and is what `ct lint` picks
up automatically):

```bash
helm lint --strict deploy/helm/provekit -f deploy/helm/provekit/ci/lint-values.yaml
helm template pk deploy/helm/provekit -f deploy/helm/provekit/ci/lint-values.yaml \
  | kubeconform -strict -kubernetes-version 1.29.0 -summary
```

## Status

Written against this repo's Dockerfiles, `compose.prod.yml`, `Caddyfile` and
`backend/provekit/config.py`, so the env vars, ports and paths are real.

**The chart has not been linted or rendered.** `helm` is not installed in the environment
this was authored in, so the commands above are the ones you should run — not ones that have
been run. The plain manifests in `../k8s` *were* checked: `kubectl kustomize deploy/k8s`
builds them successfully. Run `helm lint --strict` and `helm template` before your first
install and expect to fix something.

What that does **not** cover: nothing here has been installed on a live cluster from this
checkout, and no image has been built and pulled through it. Treat the first install as a
deployment to verify — check `/healthz`, watch the first rollout, and confirm the frontend can
reach the backend — not as a rubber stamp.
