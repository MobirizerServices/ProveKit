# ProveKit — plain Kubernetes manifests

For clusters where Helm isn't in the picture. Same topology as
[`deploy/helm/provekit`](../helm) and as `compose.prod.yml`: an ingress terminates TLS on one
hostname and routes `/api`, `/v1` and `/healthz` to the backend, everything else to the
frontend. If you do use Helm, prefer the chart — it keeps the hostname and image references in
one place instead of four.

| File | What |
|---|---|
| `00-namespace.yaml` | Namespace `provekit` |
| `10-secret.example.yaml` | Template for the two Secrets. Not applied by kustomize — see below |
| `11-configmap.yaml` | Non-secret backend config (`backend/provekit/config.py` field names) |
| `20-postgres.yaml` | Single-replica Postgres 17 + PVC |
| `21-redis.yaml` | Single-replica Redis 7, ephemeral |
| `30-backend.yaml` | Backend Deployment + Service (`backend:8000`) |
| `40-frontend.yaml` | Frontend Deployment + Service (`frontend:3000`) |
| `50-ingress.yaml` | Ingress with the `/api`, `/v1`, `/healthz` split |
| `kustomization.yaml` | Ties it together, minus the Secrets |

## Before you apply

1. **Build and push the images.** ProveKit publishes no public images.

   ```bash
   docker build -t <registry>/provekit-backend:0.1.0 backend/
   docker build -t <registry>/provekit-frontend:0.1.0 \
     --build-arg API_PROXY_TARGET=http://backend:8000 frontend/
   ```

   `API_PROXY_TARGET` is a build argument — `output: "standalone"` fixes the Next rewrite
   destination at build time. The Services here are named `backend` and `frontend` precisely so
   the image's default (`http://backend:8000`) resolves in-cluster without a rebuild.

   Then set the images, either in `kustomization.yaml` (`images:`) or by editing the `# CHANGE
   ME` lines in `30-backend.yaml` and `40-frontend.yaml`.

2. **Replace `provekit.example.com`** in `11-configmap.yaml`, `40-frontend.yaml` and
   `50-ingress.yaml`, and set an `ingressClassName` your cluster has.

3. **Create the Secrets.** They are excluded from `kustomization.yaml` so credentials never sit
   in the repo:

   ```bash
   kubectl create namespace provekit

   kubectl -n provekit create secret generic provekit-postgres \
     --from-literal=POSTGRES_USER=provekit \
     --from-literal=POSTGRES_DB=provekit \
     --from-literal=POSTGRES_PASSWORD="$PGPASS"

   kubectl -n provekit create secret generic provekit-secrets \
     --from-literal=SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
     --from-literal=DATABASE_URL="postgresql+psycopg://provekit:$PGPASS@postgres:5432/provekit" \
     --from-literal=REDIS_URL="redis://redis:6379/0"
   ```

   `SECRET_KEY` must be at least 16 characters and not a known dev default, or the backend
   refuses to start with `HOSTED=true`. `$PGPASS` is interpolated into a URL — keep it URL-safe
   or percent-encode it. Add `SENTRY_DSN` and `SMTP_PASSWORD` here too if you use them.

## Apply

```bash
kubectl apply -k deploy/k8s
kubectl -n provekit rollout status deploy/backend
curl https://provekit.example.com/healthz     # {"ok":true,...}
```

Migrations need no separate step: `alembic upgrade head` runs in the backend's startup lifespan
and takes a Postgres advisory lock first, so concurrent replicas serialize instead of racing.
The `startupProbe` allows 150s for a replica that has to wait its turn.

## Things worth knowing

- **Ports.** 8000 (backend) and 3000 (frontend) are the ports the images listen on, per their
  Dockerfiles. The 8100/3001 in `docker-compose.yml` are host publishes for local Docker.
- **The ingest spool** (`backend/provekit/services/spool.py`) fsyncs each batch to disk before
  acknowledging it, so a database blip can't destroy accepted spans. `30-backend.yaml` mounts
  an emptyDir at `/data/spool`: staged batches survive a container crash, not a pod being
  rescheduled. The spool is node-local by design — swap in a ReadWriteMany PVC, or drop to one
  replica, if you want more.
- **Redis is not optional in practice.** Rate-limit windows, playground spend counters and
  monthly span quotas live there. Without `REDIS_URL` they are per-worker and reset on restart;
  `/api/projects/usage` reports `approximate: true`.
- **`/healthz` is all three probes.** It 503s when the database (or a configured Redis) is
  unreachable, so readiness drains the pod. Liveness uses `failureThreshold: 12` — roughly four
  minutes — so a database blip doesn't restart-loop the fleet while the database recovers.
- **Postgres here has no backups.** One replica, one PVC. Point `DATABASE_URL` at a managed
  database and delete `20-postgres.yaml` before this holds anything you'd miss.
- **Quotas.** `11-configmap.yaml` ships the defaults from `backend/provekit/config.py`. If
  anyone can sign up on your instance, set `MONTHLY_SPAN_QUOTA` and
  `MAX_PROJECTS_PER_ACCOUNT` — rate limits bound bursts, not totals. See
  [docs/DEPLOY.md](../../docs/DEPLOY.md).

## Validating a change

```bash
kubectl kustomize deploy/k8s | kubeconform -strict -kubernetes-version 1.29.0 -summary
```

## Status

Written against this repo's Dockerfiles, `compose.prod.yml`, `Caddyfile` and
`backend/provekit/config.py`, so the env vars, ports and paths are real. `kubectl kustomize`
builds cleanly and all eleven resources validate against the Kubernetes 1.29 schemas
(`kubeconform -strict`).

What that does **not** cover: these manifests have not been applied to a live cluster from this
checkout, and no image has been built and pulled through them. Treat the first install as a
deployment to verify — check `/healthz`, watch the first rollout, and confirm the frontend can
reach the backend.
