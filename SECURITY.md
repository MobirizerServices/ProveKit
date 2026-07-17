# Security

## Reporting a vulnerability

Please report security issues privately to the maintainers (open a GitHub security
advisory or email the address in the repo profile) rather than a public issue. We aim to
acknowledge within 72 hours. Please include reproduction steps and the affected version.

## How AgentMan handles secrets

- **Connection credentials** (API keys, auth headers) are **encrypted at rest** with
  Fernet (`services/sealing.py`). The database never stores plaintext; the app decrypts
  on read. The key comes from `SECRET_KEY`, or an auto-generated `.agentman.key` for local
  SQLite. Hosted mode **refuses to boot** with a weak/default `SECRET_KEY`.
- **API responses mask secrets** — keys and `Authorization`-type headers are shown as
  `••••last4` (`services/masking.py`).
- **Run history masks secrets** — secret-looking fields in persisted request bodies and
  headers are masked before storage.
- **`.agentman` files never contain secrets** — connections are referenced by name and
  resolved from the environment (`${VAR}`) at run time; a file with an `api_key` is
  rejected on import.
- **Session tokens** are signed (HS256) with a `purpose` claim, so a reset/verify token
  can't be used as a session. Cookies are `HttpOnly` and `Secure` in hosted mode.

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
- **Brute force** — login and password-reset requests are rate-limited per email+IP.
- **Resource abuse** — per-workspace run rate limits, dataset-row caps, request body-size
  limits, flow-node caps, per-deployment invocation timeouts, and run-history retention.

## What is NOT yet done (be aware before exposing publicly)

- No third-party penetration test or formal audit has been performed.
- No CSP / security-header middleware on the frontend yet.
- Deployment API keys are workspace-visible; rotation is manual (redeploy).
- The SSRF guard does not defend against DNS rebinding without an egress proxy.

Run `HOSTED=true` (with a strong `SECRET_KEY`, Postgres, Redis, TLS) for any
internet-facing deployment — see `docs/DEPLOY.md`.
