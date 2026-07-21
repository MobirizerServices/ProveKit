# Security

## Reporting a vulnerability

Please report security issues privately to the maintainers (open a GitHub security advisory
or email the address in the repo profile) rather than a public issue. We aim to acknowledge
within 72 hours. Please include reproduction steps and the affected version.

## How ProveKit handles secrets

- **No plaintext secrets at rest.** ProveKit stores password hashes (PBKDF2-HMAC-SHA256) and
  project-key hashes (SHA-256) — never the plaintext. A project key (`pk_…`) is shown **once**
  at creation and only its hash is kept.
- **Session-signing key.** Session/reset/verify tokens are signed with a key derived from
  `SECRET_KEY` (or an auto-generated local key for SQLite dev), via `services/sealing.py`.
  Hosted mode **refuses to boot** unless `SECRET_KEY` is ≥16 chars and isn't a known dev
  default (`main.py`).
- **Session tokens** are signed (HS256) with a `purpose` claim, so a reset/verify token can't
  be replayed as a session. Cookies are `HttpOnly`, and `Secure` in hosted mode.
- **A password reset revokes every existing session** — tokens carry the user's
  `token_version` (`services/auth.py`), bumped on reset (`routers/auth.py`), so old sessions
  stop verifying and the reset link is single-use.
- **Provider credentials are sealed at rest.** BYO model-connection keys (OpenAI / Anthropic /
  OpenAI-compatible) are encrypted with Fernet under a `SECRET_KEY`-derived key
  (`services/sealing.py`), used only server-side, and **never returned to the browser** — the UI
  sees a masked hint (`…a1b2`) only.
- **The SDK never sends secrets.** The tracing decorator captures only the inputs/outputs of
  the traced function. Redact anything sensitive before returning it if you don't want it
  captured.
- **Optional PII redaction.** With `PROVEKIT_REDACT_PII=true` the server masks emails, cards,
  SSNs, phone numbers, and secret-key patterns in captured input/output/error *before* storage
  (`services/redact.py`). Off by default; can also be set per project.

## Threat model highlights

- **Trace ingest auth** — `/v1/traces` requires a valid bearer project key (or, for
  interactive use, a session cookie). A key resolves to exactly one project; traces are
  written only to that project.
- **Cross-tenant access** — every resource (runs, project keys) is workspace-scoped and
  checked on read, so one tenant can't see another's traces or keys.
- **SSRF** — every user-influenced outbound URL goes through `services/netguard.py` (blocks
  link-local/metadata locally; all private/internal ranges in hosted mode): the optional OTLP
  re-emit path, the **replay webhook** (`replay_url`, which the project owner sets and ProveKit
  POSTs fork overrides to), and OpenAI-compatible connection base URLs. DNS-rebinding after the
  check is a known residual risk, best closed with a pinned-egress proxy.
- **Share links** — `/shared/{token}` is deliberately public. The token is a stateless
  HMAC-SHA256 signature over `(workspace, trace, expiry)`, keyed by a share-namespaced
  derivation of the app secret, so it can't be forged or edited into a different trace, and it
  grants **read-only access to that one trace**. Default TTL is 30 days.
- **Playground / replay abuse** — re-running a call spends the project's provider credit, so
  those endpoints are rate-limited per project, capped by a hard max-tokens ceiling, and bounded
  by a monthly spend cap (`PLAYGROUND_MONTHLY_USD_CAP`, default $25) that returns 402 once
  reached. Dataset evaluations are capped to a bounded number of items per run.
- **Platform admin** — `/api/admin` is gated by `require_superuser`, a flag separate from
  project owner/member roles, bootstrappable via `SUPERUSER_EMAILS`. Superusers can see every
  user and project, so treat the flag as a platform-operator credential; a superuser cannot
  remove their own access (avoiding lockout, but meaning revocation needs another superuser).
  Note the gate is `flag OR listed email`, so a bootstrap-listed operator is revoked only by
  editing config and restarting — the API refuses such a revoke with a `409` rather than
  reporting success for a no-op. Grants are not audited. See [docs/ADMIN.md](docs/ADMIN.md).
- **Brute force** — login and password-reset requests are rate-limited per email+IP.
- **Response headers** — `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  plus HSTS in hosted mode, are set by backend middleware (`observability.py`) and again at
  the proxy (`Caddyfile`).
- **Ingest abuse** — trace ingest is rate-limited per project (`INGEST_RATE_PER_MIN`), and old
  spans are pruned to a retention cap (`RUNS_RETENTION`), so a valid key can't fill the
  database without bound. Without `REDIS_URL` the rate window is per-worker (see below).
- **Body-size limits** — request bodies are capped by middleware.

## Dependencies

- **Next.js 15** with a pinned `postcss` override — `npm audit` reports **0 vulnerabilities**,
  and CI fails on any new high/critical advisory (`npm audit --audit-level=high`).
- Python deps use compatible-release ranges; CI installs and tests them across 3.11–3.13.

## What is NOT yet done (be aware before exposing publicly)

- No third-party penetration test or formal audit has been performed.
- **No Content-Security-Policy yet** — the other security headers ship, but script sources
  aren't constrained.
- Without `REDIS_URL`, rate-limit windows are per-worker, so the effective ingest/login caps
  scale with the number of uvicorn workers — set `REDIS_URL` for hard global caps.
- Email verification/reset only sends once you configure SMTP (`SMTP_HOST`, …); until then
  the links are logged, not delivered.
- The SSRF guard does not defend against DNS rebinding without an egress proxy.
- **Share links can't be revoked individually.** The token is stateless, so the only way to
  invalidate an issued link before it expires is to rotate `SECRET_KEY` (which also invalidates
  every session). A `ttl_days <= 0` link never expires — prefer a finite TTL.

Run `HOSTED=true` (with a strong `SECRET_KEY`, Postgres, TLS) for any internet-facing
deployment — see [docs/DEPLOY.md](docs/DEPLOY.md).
