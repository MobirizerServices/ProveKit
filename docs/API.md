# HTTP API and generated clients

Everything the portal does, it does over the same HTTP API your own tools can call. FastAPI
derives an OpenAPI 3.1 description of it from the route signatures, and this repo commits that
description so you can diff it in review and generate a client from it without standing up an
instance first.

## Where the spec lives

| | |
|---|---|
| `docs/openapi.json` | the committed spec — checked for staleness in CI, safe to point a generator at |
| `GET /openapi.json` | the same document, served by a running instance |
| `GET /docs` · `GET /redoc` | Swagger UI and ReDoc, both on by default (`main.py` doesn't disable them) |

The committed copy is the one to build against. `/openapi.json` only exists if you already
have the service running, which is a bad dependency for a client build or a CI check.

## Regenerating it

```bash
python scripts/export_openapi.py            # rewrite docs/openapi.json
python scripts/export_openapi.py --check    # exit 1 if it's stale; what CI runs
python scripts/export_openapi.py --out -    # dump to stdout
```

The script imports `provekit.main:app` and calls `app.openapi()`. It never starts the server
or opens a connection, so no database, Redis, or secrets are required — from a source
checkout, `backend/venv/bin/python scripts/export_openapi.py` is enough.

Output is serialized with sorted keys on purpose. FastAPI builds `components.schemas` in
import order, so without sorting an unrelated refactor produces a large, meaningless diff and
the staleness check fails for the wrong reason.

`.github/workflows/openapi.yml` runs `--check` on every push and pull request. If a route
changes shape and the spec isn't regenerated, that job fails, prints the diff, and attaches
the regenerated file as an artifact. Fix it by running the script and committing the result.

## Authenticating

Two mechanisms, split by prefix:

| Routes | Auth | Notes |
|---|---|---|
| `/v1/*` | `Authorization: Bearer pk_...` project key | what the SDK and any external caller uses; the key resolves the project, so no project header is needed |
| `/api/*` | session cookie (`POST /api/auth/login`) | the portal's own calls; the active project comes from the `X-Project-Id` header |

`X-Project-Id` is honored only if the signed-in user is a member of that project, so it
selects a project, it doesn't grant access to one. With no header you get the user's default
project.

```bash
curl -H "Authorization: Bearer $PROVEKIT_API_KEY" \
     "$PROVEKIT_ENDPOINT/v1/traces?limit=5"
```

Local dev is `http://localhost:8000`; the Docker Compose stack publishes the backend on
`http://localhost:8100`.

## Generating a client

**TypeScript types** — `openapi-typescript` emits types only (no runtime), which suits a
frontend that already has a fetch wrapper:

```bash
npx openapi-typescript docs/openapi.json -o src/api.d.ts
```

Verified against the committed spec: it produces ~3.8k lines covering all 60 paths.

**Full clients** — `openapi-generator` emits a client with methods and models for most
languages:

```bash
npx @openapitools/openapi-generator-cli generate \
  -i docs/openapi.json -g python -o clients/generated/python
npx @openapitools/openapi-generator-cli generate \
  -i docs/openapi.json -g typescript-fetch -o clients/generated/typescript
```

> Untested here. `openapi-generator` needs a JVM, which this repo's toolchain doesn't
> otherwise require, so the commands above are written from its documented interface rather
> than from a run in this checkout. The `openapi-typescript` command was run.

Nothing in the repo consumes a generated client today, and `clients/typescript` is **not**
one — it's the hand-written `provekit` tracing SDK (`pk.trace`, `pk.span`), which talks to
`/v1/traces` and is deliberately dependency-free. Generate into a path you own.

## What the spec does and doesn't tell you

Read this before trusting a generated client. The spec is accurate about routing and about
what you send; it is close to silent about what you get back.

Across 60 paths / 76 operations:

- **Request bodies are well typed.** 27 of the 30 mutating operations declare a Pydantic
  schema. The three that don't (`POST /api/auth/logout`, `POST /api/alerts/check`,
  `POST /api/traces/{trace_id}/share`) genuinely take no body — that's correct, not a gap.
- **Responses are almost entirely untyped.** Handlers return plain `dict`s built by helpers
  like `_dataset_row()`, so FastAPI has nothing to describe and emits `schema: {}`. Exactly
  one operation in the whole API declares a response model: `POST /api/workspace/ingest-key`
  (`_KeyOut`). In practice `openapi-typescript` renders 75 of 76 responses as `unknown` —
  a generated client will make the call correctly and hand you back an opaque value.

| Group | Ops | Typed request bodies | Typed 200 responses |
|---|---|---|---|
| runs (`/api/runs`, `/api/traces`, notes, feedback, share) | 11 | 2/3 | 0 |
| datasets | 9 | 3/3 | 0 |
| experiments | 9 | 4/4 | 0 |
| playground (connections, prompts, run, replay) | 9 | 5/5 | 0 |
| projects | 8 | 3/3 | 0 |
| auth | 7 | 5/6 | 0 |
| traces (`/v1` ingest + read) | 6 | 1/2 | 0 |
| admin | 5 | 1/1 | 0 |
| alerts | 5 | 2/3 | 0 |
| api-keys | 3 | 1/1 | 0 |
| metrics | 1 | 0/0 | 0 |
| workspace | 1 | 0/1 | **1** |
| root (`/`, `/healthz`) | 2 | 0/0 | 0 |

Four structural gaps worth knowing about:

- **`POST /v1/traces` has no request body in the spec.** Ingest reads the raw `Request` so it
  can accept an OTLP `ExportTraceServiceRequest` without re-validating it, which is the right
  call for a hot path fed by standard OTel exporters — but it means a generated client gets an
  ingest method with no body parameter. Send OTLP/JSON per the OTLP spec, or use an OTel
  exporter, or the ProveKit SDK. See [TRACING.md](TRACING.md).
- **No `securitySchemes`.** Auth is enforced by dependencies that read the header or cookie
  directly, so nothing in the document declares bearer or cookie auth. Generated clients will
  not offer an auth setter; attach the `Authorization` header yourself. `authorization`
  *does* appear as an optional header parameter on the 10 key-authed operations, which is where
  the dependency happens to take it as a typed `Header`.
- **`X-Project-Id` is undocumented.** `current_workspace` reads it off the raw request, so it
  appears nowhere in the spec even though it's how a cookie-authed client picks a project.
- **`GET /api/traces/stream` is server-sent events**, not JSON, but is described as
  `application/json` like every other route. Consume it with an SSE client, not the generated
  method.

None of this is dangerous — it's a spec that under-promises. If you want a strongly typed
client, adding `response_model=` to a router is the change that pays for itself, and the
CI check above means the committed spec follows along automatically.
