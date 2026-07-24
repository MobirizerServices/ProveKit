# API stability policy

ProveKit is pre-1.0 and ships fast. That's fine for a portal you click around in; it isn't
fine for code that calls it from your CI, your agent, or your own service. This document says
exactly which surfaces you may depend on, which you may not, and what happens when one of the
dependable ones has to change.

The rule behind every line below: **a narrow promise that's kept beats a broad one that
isn't.** The covered surface is small on purpose. Everything else is honestly labelled as
internal or experimental, so you can see what you're standing on before you build on it.

## Tiers

| Tier | Surface | Promise |
|---|---|---|
| **Stable** | `/v1` trace endpoints, the Python SDK's documented top-level API | Breaking changes only after the [deprecation window](#the-deprecation-window) |
| **Experimental** | `/v1` dataset & experiment endpoints, `pk.evaluate()`, the TypeScript SDK, the MCP server | May change in any minor release, with a CHANGELOG note |
| **Internal** | `/api/*`, the database schema, span-attribute mapping, everything else | No promise at all; changes without notice |

### Stable

**HTTP — the `/v1` prefix, authenticated with a `pk_` project key as a bearer token.** This is
the surface external code integrates against, so it carries the real guarantee:

| Endpoint | What it is |
|---|---|
| `POST /v1/traces` | OTLP/HTTP-JSON ingest. Accepts an `ExportTraceServiceRequest` and returns the OTLP success shape, so a stock OpenTelemetry exporter in any language is a supported client. |
| `GET /v1/traces` | List traces (`limit`, `status`, `window_hours`, `q`, `cursor`). |
| `GET /v1/traces/{trace_id}` | Every span of one trace, in start order. |
| `POST /v1/traces/{trace_id}/feedback` · `GET …/feedback` | Attach and read scores — what `pk.score()` and offline evaluators use. |
| `GET /v1/share/{token}` | Public read of a shared trace; verifies the signed token, no key. |

`GET /healthz` is covered too, at exactly the depth a load balancer needs: a JSON body with a
boolean `ok`, returned `200` when the instance is healthy and `503` when it isn't. The other
keys in that body are operational detail and may change.

**Python SDK — the documented names in [the tracing guide](TRACING.md).** `provekit.auto`,
and from `provekit.trace`: `init()`, `configure()`, `@trace()`, `span()`, `score()`. The
environment contract (`PROVEKIT_API_KEY`, `PROVEKIT_ENDPOINT`) and the console entry points
`provekit-demo` and `provekit-doctor` are covered at the same level.

Also covered, because they are the parts most likely to be relied on silently:

- **Fail-open.** A missing key, a missing endpoint, or an unreachable portal degrades tracing
  to a no-op. Your process is never taken down by the tracer. This will not change.
- **Ingest idempotency.** Re-posting a batch does not duplicate spans, so retrying a 5xx is
  always safe.
- **Semantics of the error codes you have to branch on**: `401`/`403` (auth), `429` (rate
  limit, retry shortly), `402` (account quota, does not clear until the month rolls over),
  `503` with `Retry-After` (backpressure — retry, nothing was lost).

### Experimental

Newer surfaces that are real, tested, and shipped, but haven't been used by enough outside
code to know where their shape is wrong. **Experimental means: it may change in any minor
release, with a CHANGELOG note but no deprecation window.** Depend on these if you're willing
to read the changelog before upgrading.

- **`/v1/datasets`, `/v1/datasets/{id}/items`, `/v1/experiments`, `/v1/experiments/{id}`,
  `/v1/experiments/{id}/results`**, and `pk.evaluate()` / `provekit.scorers` on top of them.
  The evaluation model (what an experiment *is*, how results are keyed) is the part of ProveKit
  still moving most.
- **The TypeScript SDK** (`clients/typescript`, version `0.1.0`) — `init`, `trace`, `span`,
  `score`, `flush`, `shutdown`, `diagnose`, `observeOpenAI`, `observeAnthropic`. It speaks the
  same OTLP/JSON wire format to the same stable `/v1/traces`, so the *transport* is covered
  even while the client's own API isn't. Names prefixed with `_` (e.g. `_reset`) are internal
  test hooks, not API.
- **The MCP debug server** (`provekit-mcp`) — its tool names and argument shapes.
- **The `provekit` CLI** (0.7.0) — its subcommands, flags, `--json` shapes, **and its exit
  codes**, which are the part CI actually branches on: `0` pass, `1` the thing you asked about
  failed, `2` usage error, `3` refused to judge (see [CI_GATE.md](CI_GATE.md)). Experimental
  because it is one release old and its shape is unproven — but exit codes are called out
  explicitly, because a script that treats a changed code as success fails silently and green,
  which is the worst way for a gate to break. A new code may be added in a minor release; an
  existing one will not be given a new meaning without a CHANGELOG note.

A surface graduates from experimental to stable by being listed above, announced in the
CHANGELOG, and having its docs updated. Nothing graduates silently.

### Internal — explicitly not covered

- **`/api/*`.** These are cookie-authed and exist to serve the bundled frontend: runs,
  notes, share minting, metrics, alerts, projects, playground/replay, prompts, auth, admin.
  They change whenever the UI changes, in the same commit, with no notice. If you find
  yourself scripting against `/api`, that's a request for a `/v1` equivalent — open an issue
  rather than pinning a version.
- **The database schema.** Owned by Alembic; `alembic upgrade head` runs on startup. Reading
  `provekit.db` or the Postgres tables directly is unsupported, and a migration may rename or
  drop anything in them. Use the HTTP API.
- **Span-attribute internals.** ProveKit consumes `gen_ai.*` OTel attributes and maps them to
  runs (`services/otel.py`) — which aliases are accepted, how a span is classified as
  agent/llm/tool/step, and how model/provider/token fields are derived. The *input* convention
  is OpenTelemetry's, not ours; our mapping of it is an implementation detail and gets broader
  over time.
- **Python names outside the documented set**: anything under `provekit.services`,
  `provekit.routers`, `provekit.models`, and every `_`-prefixed name. Importing them is
  importing internals.
- **Route coverage in the generated OpenAPI document at `/docs`.** It describes the server you
  are talking to, internal routes included, and appearing in it is not a stability promise —
  the tiers above decide what's covered.
- **HTML, CSS, and frontend routes.** Scraping the portal is not an API.

### What counts as a breaking change

Only changes that can break a *correct* client:

- Removing an endpoint, a field, or a parameter; renaming either.
- Narrowing an accepted input, or changing a status code a client must branch on.
- Changing the type or meaning of an existing response field.

These are **not** breaking, and ship in any release: new endpoints, new optional parameters,
new response fields, new enum *values* in an existing field, and changes to human-readable
error messages (the status code is the contract; the prose isn't). Clients must ignore fields
they don't recognise — a client that rejects unknown JSON keys will break, and that is not a
regression on our side.

## Versioning

Releases are git tags `vX.Y.Z` matching `version` in `backend/pyproject.toml`; CI refuses to
publish when the two disagree, and the tag is what pushes the wheel to PyPI (see
[Publishing](PUBLISHING.md)). The current release line is `0.x`.

**Pre-1.0 (today).**

- **Patch (`0.6.0 → 0.6.1`)** never breaks anything in the stable tier.
- **Minor (`0.6.0 → 0.7.0`)** may remove something from the stable tier **only** at the end of
  the deprecation window below. It may change the experimental tier freely, and the internal
  tier without mention.
- The `/v1` prefix does not track the release number. `0.x → 0.y` does not mean `/v1 → /v2`.

**Post-1.0.** Strict semantic versioning: breaking changes to the stable tier only in a major
release, and the deprecation window still applies before the major ships. 1.0 is what the
experimental tier shrinking to (near) nothing looks like — not a date.

## The deprecation window

Before anything is removed from the **stable** tier:

> **At least 180 days, and at least two minor releases — whichever ends later.**

The calendar floor is the one that does the work. This repo has gone `0.1.0 → 0.7.0` in a
matter of weeks; a window counted only in releases could expire before you'd noticed it
opened. Two releases is the floor that stops a slow month from making the window meaningless,
not the actual promise.

During the window the deprecated thing **keeps working unchanged**. It is announced in three
places, because you shouldn't have to be reading the changelog to find out:

1. A **Deprecated** entry in [CHANGELOG.md](../CHANGELOG.md) naming the replacement and the
   removal date, repeated in every release until removal.
2. `Deprecation` and `Sunset` response headers on the affected route, both carrying an
   HTTP-date (`Sunset` is RFC 8594), so a client can detect it without a human in the loop.
   *No route emits these today — nothing is currently deprecated. The first deprecation is
   what introduces them.*
3. A `DeprecationWarning` from the Python SDK, or a one-time `console.warn` from the
   TypeScript SDK, when the deprecated path is actually used.

Self-hosters get the same window in wall-clock time; it starts when the release that announces
the deprecation is tagged, not when you upgrade.

### Worked example

Suppose we want to remove the session-cookie fallback on `POST /v1/traces`. It's real: the
key-authed routes fall back to the browser session for local single-user use
(`services/workspace.workspace_from_key`), which is convenient in dev and a wart on a surface
whose whole point is machine-to-machine auth. Removing it is a breaking change for anyone who
ingests from a logged-in browser context. It would ship like this — the releases below are
**illustrative and not scheduled**; no such deprecation is announced today:

| When | Release | What happens |
|---|---|---|
| Day 0 | `0.9.0` | **Announced.** CHANGELOG gains a *Deprecated* entry: cookie auth on `/v1/traces` is going away on 2027-01-18, use a project key. Ingest requests that authenticated by cookie come back with `Deprecation: Wed, 22 Jul 2026 00:00:00 GMT` and `Sunset: Mon, 18 Jan 2027 00:00:00 GMT`, and are logged server-side. **Behavior is unchanged — every existing client still works.** This doc and [TRACING.md](TRACING.md) are updated in the same commit. |
| Day ~45 | `0.10.0` | Still works, still warned. The *Deprecated* entry is repeated. |
| Day ~120 | `0.11.0` | Still works, still warned. Two minor releases have now passed, but the 180 days haven't — the window is not over. |
| Day 180+ | `0.12.0` | **Removed.** Cookie auth on `/v1/traces` returns `401`. CHANGELOG gains a *Removed* entry with the one-line migration: create a project key in the portal under **Project keys**, set `PROVEKIT_API_KEY`, done. |

The shape to notice: the announcement release changes nothing, the removal release is the only
one that can break you, and there are at least 180 days and one obvious upgrade path between
them.

### Emergencies

A security fix may break a stable surface immediately, without the window. That is the only
exception, it will be stated as such in the CHANGELOG and in a
[security advisory](../SECURITY.md), and the change will be the narrowest one that closes the
hole. "We really wanted to ship it" is not a security fix.

## What we ask of you

- Pin a version. `pip install "provekit[trace]==0.6.*"` and a lockfile cost nothing and mean an
  upgrade is a decision.
- Ignore response fields you don't recognise.
- Retry `5xx` and `503`; don't retry `4xx` (except `429`, after the delay).
- Read the CHANGELOG before a minor bump. That's where deprecations live.
