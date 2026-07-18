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
- **The SDK never sends secrets.** The tracing decorator captures only the inputs/outputs of
  the traced function. Redact anything sensitive before returning it if you don't want it
  captured.

## Threat model highlights

- **Trace ingest auth** — `/v1/traces` requires a valid bearer project key (or, for
  interactive use, a session cookie). A key resolves to exactly one project; traces are
  written only to that project.
- **Cross-tenant access** — every resource (runs, project keys) is workspace-scoped and
  checked on read, so one tenant can't see another's traces or keys.
- **SSRF** — the optional OTLP re-emit path guards outbound URLs through
  `services/netguard.py` (blocks link-local/metadata locally; all private/internal ranges in
  hosted mode). DNS-rebinding after the check is a known residual risk, best closed with a
  pinned-egress proxy.
- **Brute force** — login and password-reset requests are rate-limited per email+IP.
- **Response headers** — `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  plus HSTS in hosted mode, are set by backend middleware (`observability.py`) and again at
  the proxy (`Caddyfile`).
- **Body-size limits** — request bodies are capped by middleware to bound ingest abuse.

## Dependencies

- **Next.js 15** with a pinned `postcss` override — `npm audit` reports **0 vulnerabilities**,
  and CI fails on any new high/critical advisory (`npm audit --audit-level=high`).
- Python deps use compatible-release ranges; CI installs and tests them across 3.11–3.13.

## What is NOT yet done (be aware before exposing publicly)

- No third-party penetration test or formal audit has been performed.
- **No Content-Security-Policy yet** — the other security headers ship, but script sources
  aren't constrained.
- **No rate limit on trace ingest** — a valid key can write unbounded traces; add per-project
  ingest limits before opening a public hosted instance.
- SMTP isn't wired, so email-verification/reset messages aren't actually sent until you
  configure a provider.
- The SSRF guard does not defend against DNS rebinding without an egress proxy.

Run `HOSTED=true` (with a strong `SECRET_KEY`, Postgres, TLS) for any internet-facing
deployment — see [docs/DEPLOY.md](docs/DEPLOY.md).
