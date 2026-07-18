# Security

## Reporting a vulnerability

Please report security issues privately to the maintainers (open a GitHub security
advisory or email the address in the repo profile) rather than a public issue. We aim to
acknowledge within 72 hours. Please include reproduction steps and the affected version.

## How ProveKit handles secrets

- **Connection credentials** (API keys, auth headers) are **encrypted at rest** with
  Fernet (`services/sealing.py`). The database never stores plaintext; the app decrypts
  on read. The key comes from `SECRET_KEY`, or an auto-generated `.provekit.key` for local
  SQLite. Hosted mode **refuses to boot** unless `SECRET_KEY` is at least 16 characters and
  isn't one of the known dev defaults (`main.py`). Running a non-SQLite database with a weak
  key and `HOSTED=false` boots, but logs a loud warning.
- **API responses mask secrets** — keys and `Authorization`-type headers are shown as
  `••••last4` (`services/masking.py`).
- **Run history masks secrets** — secret-looking fields in persisted request bodies and
  headers are masked before storage.
- **`.provekit` files never contain secrets** — connections are referenced by name and
  resolved from the environment (`${VAR}`) at run time; a file with an `api_key` is
  rejected on import.
- **Session tokens** are signed (HS256) with a `purpose` claim, so a reset/verify token
  can't be used as a session. Cookies are `HttpOnly` and `Secure` in hosted mode.
- **A password reset revokes every existing session** — tokens carry the user's
  `token_version` (`services/auth.py`), which is bumped on reset (`routers/auth.py`), so
  old sessions stop verifying and the reset link itself is single-use. Completing a reset
  also marks the email verified: receiving the link proves the same mailbox control the
  verification link tests, and the revocation would otherwise invalidate the one verify
  link a user is ever sent.

## Threat model highlights

- **SSRF** — all outbound URLs (LLM, MCP, HTTP agent, A2A, OAuth token, OTLP emit) pass
  through `services/netguard.py`. Local mode blocks link-local/metadata; **hosted mode
  blocks all private/internal ranges and resolves DNS** before connecting. DNS-rebinding
  after the check is a known residual risk best closed with a pinned-egress proxy.
- **Credential exfiltration** — a stored connection is authoritative for both destination
  and credentials; per-request `base_url`/`api_key`/header overrides are ignored when a
  `connection_id` is used, so a caller can't point a stored key at their own host.
- **Cross-tenant access** — every resource is workspace-scoped; connection resolution in
  the run/flow/judge paths is workspace-checked, so one tenant can't run against another's
  stored credentials by passing an id.
- **Local code execution (stdio MCP)** — an MCP connection can name a local command to
  spawn. Hosted mode **refuses to launch one at all** (`netguard.guard_stdio()`, enforced in
  `providers/mcp_client.py`), so a signed-up tenant can't turn a connection into remote code
  execution on the server. Local mode keeps stdio, where it's your own machine by design.
- **Brute force** — login and password-reset requests are rate-limited per email+IP.
- **Response headers** — `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, plus HSTS in hosted mode, are set by backend middleware
  (`observability.py`) and again at the proxy for every response (`Caddyfile`).
- **Resource abuse** — per-workspace run rate limits, dataset-row caps, request body-size
  limits, flow-node caps, per-deployment invocation timeouts, and run-history retention.

## Known dependency advisories

- **Next.js** is pinned to `14.2.35`, which clears the critical December 2025 advisory.
  Two lower-severity advisories remain (1 high, 1 moderate/postcss), both DoS/cache-class
  and only fixed in Next 16 — a two-major upgrade that requires migrating the client-hook
  pages (`/forgot`, `/reset`, `/verify`) and is tracked as follow-up work, not a
  pre-launch rush. When ProveKit runs behind the reverse proxy in `docs/DEPLOY.md`, the
  proxy mitigates the request-smuggling/cache-poisoning classes. Run `npm audit` to review.

## What is NOT yet done (be aware before exposing publicly)

- No third-party penetration test or formal audit has been performed.
- **No Content-Security-Policy yet.** The other security headers ship (see above), but
  nothing constrains script sources, so an injected script is not defence-in-depth'd.
- Deployment API keys are workspace-visible; rotation is manual (redeploy).
- The SSRF guard does not defend against DNS rebinding without an egress proxy.
- Next.js 16 upgrade pending (see dependency advisories above).

Run `HOSTED=true` (with a strong `SECRET_KEY`, Postgres, Redis, TLS) for any
internet-facing deployment — see `docs/DEPLOY.md`.
