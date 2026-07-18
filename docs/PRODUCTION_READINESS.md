# ProveKit — Production-Readiness Plan (100 points)

> Compiled from an 8-track code audit (security, reliability, testing/CI, packaging, data,
> deployment/ops, API/frontend, docs/launch) reading the real code. Each item is tagged:
> **P0** = ship-blocker (fix before real users), **P1** = before a broad launch,
> **P2** = hardening. File anchors are the current tree (`backend/provekit/…`).
>
> Two agent claims were corrected during synthesis: migrations *are* run on boot
> (`database.py init_db → _run_migrations`), and a `LICENSE` *does* exist at the repo root —
> the real gap is that it isn't bundled in the wheel (#69).

## The 7 ship-blockers (P0) — do these first

- **#52** Coverage isn't gated in CI (can regress silently).
- **#53** `publish.yml` ships to PyPI with no test gate.
- **#66** The pip CLI drags in the whole server stack.
- **#67** Hard `==` pins on a distributed library cause install conflicts.
- **#17** MCP stdio has no read timeout → shared threadpool exhaustion.
- **#14** Next.js 14.2.35 ships with 2 open advisories.
- **#87** README demo GIF (the value-prop visual) is missing.

---

## A. Security, auth, tenancy & secrets

1. **[P1]** Sentry captures decrypted secrets from stack-frame locals (`include_local_variables` default true, no `before_send`, no `environment`/`release`). Fix: `include_local_variables=False`, `send_default_pii=False`, a redacting `before_send`. `observability.py:47`
2. **[P1]** Logout doesn't revoke the 30-day session token — it only deletes the cookie; the signed token stays valid until a password reset. Fix: bump `token_version` on logout (or a jti denylist) + shorter TTL with refresh. `routers/auth.py:77`
3. **[P1]** Rate limits fall back to per-worker memory when `REDIS_URL` is unset in hosted mode → login throttle × workers. Fix: require `REDIS_URL` when `HOSTED=true`. `services/limits.py:51`
4. **[P1]** Unbounded password length → PBKDF2 CPU-exhaustion DoS on `/register`,`/login` (2 MB body admitted). Fix: reject `len(password) > ~128` in the model. `services/auth.py:47`
5. **[P2]** Registration leaks account existence (`409` on existing email) — defeats the enumeration hardening on login/forgot. Fix: generic success + email an "already exists" notice. `routers/auth.py:46`
6. **[P2]** Deployment API keys can't be rotated — redeploy reuses the old hash; SECURITY.md's "rotation is manual (redeploy)" is factually wrong. Fix: add a `rotate-key` endpoint. `routers/deployments.py:46`
7. **[P2]** Fernet key = single unsalted SHA-256 of `SECRET_KEY` (no KDF), and the same secret signs sessions. Fix: scrypt/PBKDF2 + stored salt; mandate a 32-byte key. `services/sealing.py:41`
8. **[P2]** Brute-force throttle keyed on `email:ip` → password-spray/botnet bypass. Fix: per-account failure counter with backoff, independent of IP. `routers/auth.py:62`
9. **[P2]** `POST /v1/traces` ingest has no rate limit and skips retention → a leaked ingest key can flood the Run table. Fix: per-workspace rate limit + span cap. `routers/traces.py:37`
10. **[P2]** `mask_value` reveals the last 4 chars of every secret, including short ones. Fix: only reveal last-4 when `len >= 12`. `services/masking.py:22`
11. **[P2]** Public runtime returns `404` vs `410` as a deployment-existence oracle over guessable slugs. Fix: uniform `404`. `routers/runtime.py:30`
12. **[P2]** Security headers omit COOP/CORP/Permissions-Policy; HSTS lacks `preload`. Fix: add them. `observability.py:70`
13. **[P2]** `.provekit.key` is written next to the SQLite DB — one folder/backup copy defeats at-rest encryption. Fix: externalize the key path + document. `services/sealing.py:47`

## B. Web-app security & headers

14. **[P0]** Next.js pinned to 14.2.35 with 2 acknowledged open advisories. Fix: upgrade to the latest 14.2.x patch (or Next 16); add `npm audit`/Dependabot; gate release on zero high. `frontend/package.json:11`
15. **[P1]** No CSP / security headers on the Next-served HTML — the middleware only stamps API responses, so the pages rendering user data have no CSP/frame/referrer protection. Fix: a `headers()` block in `next.config.js`. `next.config.js`
16. **[P1]** OpenAPI `/docs`, `/redoc`, `/openapi.json` exposed unauthenticated in prod (and `root()` advertises `/docs`). Fix: disable when `hosted`, or gate behind auth. `main.py:78,110`

## C. Reliability & resilience

17. **[P0]** MCP stdio transport has no read timeout — a hung server blocks a threadpool thread forever, wedging the shared 200-thread pool (DB writes, assertions, persist all offload there). Fix: read deadline via select/poll, kill on expiry. `services/providers/mcp_client.py:96,107`
18. **[P1]** No overall wall-clock cap on `/api/run/stream` or the streaming deployment path (`deployment_timeout_s` guards only the non-stream branch); 25 tool rounds × per-read-only timeouts can run tens of minutes. Fix: a run-level deadline on both streaming paths. `routers/run.py:121`, `runtime.py:65`
19. **[P1]** httpx timeouts are per-read-gap only (never a total budget) and uneven/hardcoded (120/30/15s). Fix: `httpx.Timeout(connect,read)` + an outer deadline; make configurable. `services/providers/llm.py:197`
20. **[P1]** No retries/backoff on transient upstream failures (429/5xx) — one blip fails the whole run. Fix: bounded retry with backoff+jitter, respect `Retry-After`, pre-stream. `services/providers/*`
21. **[P1]** Redis is called synchronously on the event loop with no socket timeout and no fallback (`store_ctx`/`pop_ctx` inside the async generator). Fix: socket timeouts, offload to a thread, degrade gracefully. `services/runstore.py:51`, `services/flow.py:255`
22. **[P1]** Error messages leak upstream internals (raw provider bodies, URLs) to unauthenticated deployment callers over SSE and the 504 JSON — and raw `str(exc)` reaches the UI. Fix: log detail server-side by `request_id`, return a sanitized generic message. `llm.py:200`, `routers/connections.py:162,255,270`
23. **[P1]** Unbounded response buffering in the MCP (`resp.text`, stdio lines) and A2A clients → a hostile server can OOM the worker. Fix: byte-ceiling streaming on all transports (mirror agent_http's 16 MB cap). `mcp_client.py:132`, `a2a_client.py:100`
24. **[P1]** Unbounded concurrent stdio subprocess spawns — no global cap (per attachment + per connection per run). Fix: bounded semaphore/pool. `services/tooling.py:105,160`
25. **[P1]** `/healthz` conflates liveness and readiness — a transient DB/Redis blip 503s and crash-loops every pod. Fix: split `/livez` (always 200) and `/readyz` (dep-checked). `observability.py:135`
26. **[P2]** Agent-HTTP streaming has no line-length or total-bytes cap. Fix: cap per-line and cumulative bytes. `services/providers/agent_http.py:29`
27. **[P2]** No circuit breaking on repeatedly-failing/slow upstreams — requests pile on the shared pool during an outage. Fix: per-destination circuit breaker.
28. **[P2]** No graceful shutdown / draining of in-flight streams and subprocesses on SIGTERM — redeploy hard-kills active runs and orphans stdio processes. Fix: a shutdown phase that stops new work, drains bounded, terminates tracked subprocesses. `main.py:59`
29. **[P2]** Client disconnect can't cancel an in-flight blocking MCP tool call (non-cancellable thread) — may fire a real side-effecting tool after the caller left. Fix: bound the thread with a timeout/cancellation scope. `dispatch.py:233`

## D. Data, migrations & performance

30. **[P1]** `workspace_id` is nullable on every tenant table — a NULL row escapes all scoped reads and pruning (tenancy leak). Fix: `NOT NULL` migration + backfill/reject. `models.py:11`
31. **[P1]** Run list/history has no composite index for its filter+sort path. Fix: `(workspace_id, id desc)` and `(deployment_id, id desc)`. `routers/run.py:190`
32. **[P1]** `prune_runs` runs on the hot write path (OFFSET scan + extra commit per insert) — doubles write transactions. Fix: probabilistic or periodic pruning by id/created_at cutoff. `services/limits.py:99`
33. **[P1]** Deployment invocations (`/v1/d`) never prune → unbounded run growth on the highest-traffic path. Fix: prune after the deployment save, or a periodic job. `routers/runtime.py:91`
34. **[P1]** Run bodies (`request`/`result` incl. the full events list) are stored with no size cap → table bloat. Fix: truncate persisted events/output; out-of-row/compress large payloads. `models.py:186`
35. **[P1]** Postgres pool over-provisioned: `20 + 200 overflow = 220`/worker → `--workers 4` requests 880 vs Postgres's default ~100 → `too many connections`. Fix: sane per-worker budget sized against `max_connections/workers`; add `pool_recycle`/`pool_timeout`. `database.py:16`
36. **[P1]** Migration-on-boot advisory lock is Postgres-only; multi-process file-SQLite races on `alembic_version`. Fix: a file lock on the SQLite path, or require single-process migration on SQLite. `database.py:100`
37. **[P1]** `deployments.slug` uniqueness is a racy read + non-unique index (TOCTOU) — concurrent first-publishes can collide on a public endpoint. Fix: `UNIQUE(slug[,version])` + integrity-error retry. `routers/deployments.py:63`
38. **[P2]** Usage window scans unindexed `runs.created_at` and hydrates full Run rows (large JSON) to sum ints. Fix: index `(workspace_id, created_at)`; store token counts in dedicated columns. `routers/usage.py:28`
39. **[P2]** Aggregation done in Python + no DB `statement_timeout` — one big workspace can pin a pooled connection. Fix: `statement_timeout` in `connect_args`; push counts/percentiles into SQL. `routers/usage.py:31`
40. **[P2]** Down-migrations exist but are untested; SQLite downgrade is a table-rebuild; the `_ADOPT_BY_COLUMN` stamping heuristic is fragile. Fix: CI test upgrade→downgrade→upgrade on SQLite + Postgres. `database.py:67`
41. **[P2]** No backup/restore guidance; SQLite↔Postgres drift (naive-UTC datetimes, no JSON operators). Fix: backup/restore + WAL-checkpoint section; `TIMESTAMPTZ` on Postgres; document JSON limits. `docs/DEPLOY.md`

## E. Deployment & operations

42. **[P1]** No metrics/observability endpoint (only `healthz`) — blind between "up" and "down"; `otel_export_url` is defined but never wired. Fix: a Prometheus endpoint or wire the OTLP export path. `observability.py:135`
43. **[P1]** No resource limits or restart policies in compose — a leak/runaway can OOM the host and take down co-located containers. Fix: `deploy.resources.limits` + `restart: unless-stopped`. `compose.prod.yml`
44. **[P1]** Weak/default secrets in compose (`SECRET_KEY=dev-only-change-me`, Postgres `provekit/provekit`) passed as plain env — a `HOSTED=false` Postgres copy encrypts all creds under a public constant. Fix: file-mounted secrets; never ship a usable SECRET_KEY default. `docker-compose.yml:34`
45. **[P1]** No DB backup / volume snapshot for `provekit-pg` — volume loss or a bad migration = unrecoverable multi-tenant data loss. Fix: scheduled off-host `pg_dump` + documented restore. `compose.prod.yml:86`
46. **[P2]** Log level hardcoded `INFO` with no env knob; no aggregation target. Fix: a `LOG_LEVEL` setting; document stdout→aggregator. `observability.py:35`
47. **[P2]** Floating base images (`python:3.13-slim`, `node:20-slim`) and no `HEALTHCHECK` in the Dockerfiles. Fix: pin by digest; add `HEALTHCHECK`. `backend/Dockerfile:2`
48. **[P2]** `.dockerignore` gaps — root is empty; frontend misses `.git`/`tests` while its Dockerfile does `COPY . .` (whole tree incl. `.git` enters the build context). Fix: complete both `.dockerignore` files. `frontend/Dockerfile:6`
49. **[P2]** Multi-worker correctness undocumented — Redis is optional but required for >1 worker's flow state; no scaling/stickiness doc; no startup guard. Fix: document + guard `workers>1` with empty `redis_url`. `compose.prod.yml:48`
50. **[P2]** No edge rate limiting or streaming-tuned proxy timeouts in Caddy — pre-auth floods (login, public deploys) hit the backend directly. Fix: Caddy `rate_limit` + explicit reverse-proxy timeouts for SSE. `Caddyfile`
51. **[P2]** No `security.txt`, external uptime monitoring, or a generated env-var reference (~30 settings). Fix: serve `/.well-known/security.txt`; add uptime monitoring + alerting; generate the env reference from `Settings`.

## F. Testing, CI/CD & release

52. **[P0]** Coverage measured locally but never gated (or run) in CI — `pytest-cov` absent from dev deps; `[tool.coverage]` orphaned; a PR can drop tests and stay green. Fix: add `pytest-cov`, run `--cov` in CI, `fail_under` gate. `.github/workflows/ci.yml:26`
53. **[P0]** `publish.yml` ships to PyPI on any `v*` tag with no test/lint gate — a bad commit publishes an immutable release. Fix: gate publish on the test/lint jobs (`needs:`). `.github/workflows/publish.yml`
54. **[P1]** CI runs a single Python (3.13) while the package claims 3.11–3.13 (publish even builds on 3.12) — exactly how a 3.13-only flake slipped through. Fix: matrix `3.11/3.12/3.13`. `ci.yml:15`
55. **[P1]** No dependency vulnerability scanning (no pip-audit/Dependabot) despite hard-pinned deps + no `npm audit`. Fix: `dependabot.yml` (pip+npm+actions) + a `pip-audit` step.
56. **[P1]** Frontend has no tests at all (only `tsc`+build). Fix: Vitest + React Testing Library for `components/`+`lib/`.
57. **[P1]** Frontend lint not gated — no ESLint config/dep; `next build` silently skips linting. Fix: ESLint config + a CI lint step.
58. **[P2]** No real-provider smoke test — tool-calling only tested vs synthetic SSE; a provider wire-shape change breaks prod while tests stay green. Fix: an opt-in `@integration` test gated on real keys, run nightly/pre-release.
59. **[P2]** No load/perf test for the hosted deploy API (`POST /v1/d/{slug}`). Fix: a Locust/k6 smoke in a scheduled workflow.
60. **[P2]** No pre-commit hooks — lint/format/secrets run only in CI. Fix: `.pre-commit-config.yaml` (ruff, ruff-format, whitespace, secrets).
61. **[P2]** No release/version automation; `pyproject` + `package.json` hand-synced; permanent `## Unreleased`; tag not checked against `pyproject` version (a `v0.2.0` tag would publish a `0.1.0`-stamped wheel). Fix: tag-vs-version assertion + release-please/towncrier.
62. **[P2]** The docker CI job only builds images, never runs them — a container that builds but crashes on boot passes CI. Fix: `docker run` + `/healthz` curl; add a Playwright login→flow→deploy e2e.
63. **[P2]** CI has no concurrency-cancel, no `timeout-minutes`, no least-privilege `permissions:`. Fix: `concurrency` cancel-in-progress, `permissions: contents: read`, per-job timeouts.
64. **[P2]** No SBOM, build provenance/attestations, or secret scanning. Fix: `attestations: true` on publish, generate an SBOM, add a gitleaks job.
65. **[P2]** Fragile test isolation — one shared session-wide SQLite DB + `asyncio.run` on a shared engine, no `pytest-randomly` → hidden order-dependence (the 3.13 flake). Fix: `pytest-randomly` + function-scoped DB isolation. `tests/conftest.py`

## G. Packaging & distribution

66. **[P0]** The CLI wheel force-installs the entire server stack (14 deps for a ~5-dep CLI). Fix: minimal core deps + a `provekit[server]` extra. `backend/pyproject.toml:22`
67. **[P0]** Hard `==` pins on a distributed library guarantee resolution conflicts for anyone with a different httpx/pydantic/cryptography. Fix: compatible-release/floor specifiers in `Requires-Dist`; keep `==` only in the deployment lock. `pyproject.toml:23`
68. **[P1]** No upper-bound strategy once pins loosen — a bare `>=` will pull an untested breaking major (pydantic 2→3). Fix: a documented `>=tested,<next-major` policy.
69. **[P1]** `LICENSE` isn't bundled in the wheel (it's at the repo root, not next to `pyproject` in `backend/`, and there's no `license-files` directive); MIT requires the text accompany distributions. Also no transitive-dep license audit. Fix: `license-files`, ensure LICENSE ships; run `pip-licenses`.
70. **[P1]** `requirements.txt` duplicates `pyproject` deps and Docker installs from it (never installs the package) → image and pip users can silently diverge; no lockfile. Fix: single source (`uv pip compile`), Docker `pip install .[server]`, commit a hash-pinned lock.
71. **[P1]** No hashes / `--require-hashes` anywhere — a compromised index artifact installs unchallenged. Fix: hash-locked requirements + `--require-hashes` in Docker/CI.
72. **[P1]** No `py.typed` marker despite fully-typed code → downstream mypy/pyright get no type info. Fix: add `provekit/py.typed` to `package-data`.
73. **[P1]** The CLI surfaces raw tracebacks on ordinary user errors (missing config, malformed YAML) — reads as bugs for a CI tool. Fix: top-level try/except → `error: <msg>` + exit 2. `cli.py:221,66,251`
74. **[P2]** No `--version` flag and no `__version__` (empty `__init__.py`). Fix: `importlib.metadata` version + `--version`.
75. **[P2]** No shell completion for the subcommands. Fix: `argcomplete` or generated completions.
76. **[P2]** SemVer/version policy undocumented; version single-sourced only in `pyproject`. Fix: document the policy; dynamic version from metadata.

## H. API design & frontend UX

77. **[P1]** No API versioning on the internal `/api` surface (only `/v1` for deploys) — a shape change breaks every deployed browser build with no migration window. Fix: mount under `/api/v1` (keep `/api` alias); centralize the version in `lib/api.ts`.
78. **[P1]** Inconsistent error schema across routers (`detail` vs `{ok:false}` vs ad-hoc; `200`-with-`status:failed`) — the frontend can't branch on a stable contract. Fix: one error envelope via a global handler; non-2xx for failures.
79. **[P1]** List endpoints return unbounded result sets (connections/collections/environments/prompts/flows/datasets; collections eagerly loads every request row). Fix: `limit`/`cursor` with clamped defaults; paginate the UI.
80. **[P1]** No `max_length`/size validation on string & nested dict fields (`name`/`config`/`variables`) — a 2 MB name or deeply-nested config is accepted and persisted. Fix: `constr(max_length)` + bound dict size/depth.
81. **[P1]** No request timeout/retry in `lib/api.ts` fetch — a hung backend leaves promises pending forever with no feedback. Fix: `AbortSignal.timeout` + retry idempotent GETs.
82. **[P1]** Accessibility gaps on the flow canvas — nodes are non-focusable divs (no role/tabIndex/aria/keyboard); icon buttons rely on `title` not `aria-label`; no focus management when the inspector opens. Fix: focusable nodes with role/aria-label; aria on icon buttons; focus into inspector. `FlowNode.tsx:57`
83. **[P2]** Missing route-level loading states — no `loading.tsx`/`not-found.tsx`; client-fetch pages flash empty (indistinguishable from "no data"). Fix: loading skeletons + not-found; distinguish loading vs empty.
84. **[P2]** Shallow/silent degraded handling — some loaders swallow errors; SSE streams throw on a mid-stream drop with no reconnect/resume (the backend supports `continue/stream`). Fix: surface load failures; SSE reconnect with `run_id` resume.
85. **[P2]** Whole app is client-rendered; React Flow is imported statically at the flows route top → in first-load JS before a flow opens. Fix: `next/dynamic(ssr:false)` for the editor + modals; lazy-load.
86. **[P2]** No `X-RateLimit-*` headers on 2xx (only `Retry-After` on 429) — clients can't back off proactively. Fix: emit rate-limit headers.

## I. Docs, community, launch & legal

87. **[P0]** README demo GIF is an empty placeholder — the core "run → assert → CI" value-prop visual is missing; a cold visitor sees a wall of text. Fix: record the 90s take, drop `docs/launch/demo.gif`, uncomment the `<img>`. `README.md:18`
88. **[P1]** No `CODE_OF_CONDUCT.md`. Fix: Contributor Covenant 2.1 + a real enforcement contact.
89. **[P1]** No GitHub issue/PR templates. Fix: `bug_report.yml` + `feature_request.yml` + a PR template.
90. **[P1]** CONTRIBUTING has no release-process section (the mechanism only lives as a comment in `publish.yml`). Fix: a "Cutting a release" section.
91. **[P1]** SECURITY.md disclosure has no real contact or PGP (says "email the address in the repo profile" — none exists) while promising a 72h ack. Fix: name a real security alias or designate GitHub Security Advisories.
92. **[P1]** No versioning/deprecation policy — teams commit `.provekit` files into CI, so a silent format break breaks their pipelines. Fix: a VERSIONING section (SemVer + file-format compat promise + deprecation window).
93. **[P1]** No PRIVACY/telemetry statement backing the "no telemetry" promise (true in code, but undocumented, and the operator-Sentry nuance is unstated). Fix: a short PRIVACY doc, linked from the promise.
94. **[P1]** README quickstart still says `pip install -e backend` instead of the shipped `pip install provekit`. Fix: update it; keep `-e backend` only as a contributor note. `README.md:136`
95. **[P1]** CHANGELOG has no dated `[0.1.0]` entry despite the shipped tag — all under `## Unreleased`. Fix: rename to `## [0.1.0] — 2026-07-18`; open a fresh `## Unreleased`.
96. **[P1]** **Brand collision: "ProveKit" is already an OSS zero-knowledge proving toolkit (`worldfnd/ProveKit`, 108★, verified).** The pip/npm/GitHub-org names were free, but the *name* collides in adjacent dev-tooling → SEO dilution + confusion. Fix: decide now whether to differentiate before amplifying the launch.
97. **[P2]** Self-host guide lacks an upgrade/backup/rollback runbook (only first-deploy). Fix: "Upgrading" + "Backup & restore" subsections in `DEPLOY.md`.
98. **[P2]** No public ROADMAP; internal strategy docs (`PRODUCT_STRATEGY`, `CUSTOMER_DISCOVERY`) are linked as public docs — exposing go-to-market thinking. Fix: a lightweight public ROADMAP; reconsider whether strategy/discovery belong in the public tree.
99. **[P2]** No `CITATION.cff` or `GOVERNANCE` — no maintainer/decision-process signal; framed as solo. Fix: a GOVERNANCE note + `CITATION.cff`.
100. **[P2]** Keep the repo lean for clones — confirm no venvs/build artifacts are tracked (a stray `.venv_win` was noted; `dist/`/`build/` are now gitignored). Fix: verify `git ls-files` is clean.

---

## Already solid (verified — don't re-audit)

- **SSRF**: `guard_url` at every outbound entry point, `follow_redirects=False`; `guard_stdio` RCE gate in hosted mode.
- **Tenancy**: `current_workspace` scoping consistent across routers; connection resolver workspace-checked.
- **Auth**: HMAC-SHA256 JWT (no alg-confusion), dummy-hash login timing equalizer, hashed deploy keys with `compare_digest`, reset revokes sessions + verifies email.
- **Migrations**: run on boot for every persistent DB, serialized on Postgres by an advisory lock; ship inside the wheel.
- **Streaming**: run persistence offloaded off the event loop; disconnect-persist path present; body-size 413 + flow-node caps + run-list clamps in place.
- **Frontend**: `error.tsx`/`global-error.tsx` boundaries wired; the health-poll down-banner works.
- **"No telemetry" claim is true in code**: no phone-home; Sentry/OTel are operator-opt-in.

## How to sequence it

**Before real users (P0):** #52, #53, #66, #67, #17, #14, #87.
**Before a broad/public launch (the P1s):** the security, reliability, data-integrity, and packaging P1s above — especially tenancy `NOT NULL` (#30), the connection-pool sizing (#35), CSP (#15), API versioning (#77), the LICENSE-in-wheel (#69), and the brand decision (#96).
**Ongoing hardening (P2):** everything else.
</content>
