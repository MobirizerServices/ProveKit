# Region & data residency

Where ProveKit's data physically lives, what leaves the machine, what you control, and what an
EU-resident deployment would actually require.

This page describes **what the code does**, verified against the source. It makes no compliance
claims and is not legal advice: ProveKit is software you run, not a certified service, and
nothing here is a DPA, an SCC, or an attestation. Where a decision depends on a third party
(your model provider, your mail provider), this page says so instead of guessing.

---

## The short answer

**ProveKit is single-region by construction, and the region is wherever you run the container.**

There is no ProveKit control plane, no ProveKit-operated storage, and no telemetry back to the
project. The stack in `compose.prod.yml` is one host: Caddy, the Next.js frontend, the FastAPI
backend, one Postgres, one Redis. Every trace you ingest is written to the Postgres volume on
that host and read back from it. If that host is in Frankfurt, your traces are in Frankfurt.

The corollary is the honest limitation: there is also **no multi-region support, no per-workspace
data pinning, and nothing in the code that enforces residency**. Residency is a property of where
you deploy and what you configure, not something ProveKit checks for you.

---

## Where data physically lives

Everything below is on the deployment host unless you moved it.

| Data | Where | Contains |
|---|---|---|
| Traces, spans, inputs/outputs, scores, feedback, notes | Postgres — `provekit-pg` Docker volume | the substance: prompts, model outputs, tool arguments, whatever your agent passed through |
| Users, workspaces, memberships, audit log | same Postgres | emails, PBKDF2 password hashes, role assignments |
| API keys | same Postgres | SHA-256 hashes only — the key itself is shown once and never stored |
| Provider credentials (OpenAI/Anthropic keys you paste into Settings) | same Postgres | Fernet-sealed under `SECRET_KEY` (`services/sealing.py`); never returned to the browser |
| Datasets, experiments, prompt versions, saved views | same Postgres | your evaluation data |
| Ingest spool | `SPOOL_DIR`, default a system temp dir (`services/spool.py`) | in-flight OTLP batches, on disk, until the rows commit — seconds of data |
| Rate-limit windows, spend counters | Redis | counters, no trace content |
| Backups | `BACKUP_DIR`, default `/root/provekit-backups` | a full copy of Postgres. See [BACKUP.md](BACKUP.md) — this is the copy people forget when they reason about residency |
| TLS certificates | `caddy-data` volume | Let's Encrypt material |
| Logs | container stdout | JSON lines with `request_id`. **Traced inputs/outputs are never logged by the server** |

Your agents' data crosses the network exactly once on the way in: the SDK POSTs OTLP to
`PROVEKIT_ENDPOINT`, which is a value *you* set. The SDK has no default endpoint — with
`PROVEKIT_ENDPOINT` unset, tracing is disabled and nothing is sent anywhere
(`provekit/trace.py`).

---

## What leaves the box

Every outbound URL in the server goes through `services/netguard.py`, which in hosted mode
blocks private/reserved/link-local addresses and DNS-resolves hostnames first. That is an SSRF
control, not a residency control — it stops the server reaching *inward*, not outward.

Here is the complete list of things that make outbound connections, all of them off or absent
by default except the last two:

### 1. Model provider calls — the one that matters

`services/llm_client.py` calls providers directly over HTTPS:

- `openai` → `https://api.openai.com/v1/chat/completions`
- `anthropic` → `https://api.anthropic.com/v1/messages`
- `openai_compatible` → **any `base_url` you configure**
- `mock` → no network at all

**What is sent:** the full `messages` array — system prompt, user content, assistant turns —
plus model and parameters. This is your prompt content leaving your region.

**When it happens:** only on *re-runs*, never on ingest. The paths are the playground,
`services/replay.py` (trace forking), experiments, and `llm_client.judge()` for model-graded
scoring. **Ingesting a trace never calls a provider.** An instance where nobody has connected a
provider key makes zero provider calls — the code raises `missing API key for this connection`
rather than falling back to anything.

Note the asymmetry that trips people up: your *agent* already sends prompts to OpenAI/Anthropic
from wherever it runs — ProveKit observing it doesn't add egress. But re-running a trace in the
portal is a *new* call, originating from the ProveKit host, on data now at rest in your database.

### 2. OTLP re-emit — off unless `OTEL_EXPORT_URL` is set

`services/otel.py` forwards a span to a downstream collector. The body is metadata only: span
name, operation type, provider name, model name, token counts, status. **No inputs or outputs.**

### 3. Alert webhooks — off unless a project configures one

`services/notify.py` posts to Slack, Discord, PagerDuty (incl. `events.eu.pagerduty.com`), or
Opsgenie (incl. `api.eu.opsgenie.com`). The body is the breach message built in
`routers/alerts.py`: metric name, value, comparator, threshold, window, and the project name.
**No trace content.**

### 4. Replay webhook — off unless a project sets `replay_url`

`services/replay.py` POSTs `{origin_trace_id, fork_span_id, overrides}` to your own endpoint so
your real agent re-runs. `overrides` is prompt content you chose to change. The destination is
yours.

### 5. SMTP — off unless `SMTP_HOST` is set

`services/email.py`. Recipient addresses, password-reset and verification links, sent through
your mail provider. Without SMTP configured, hosted mode refuses to send and logs an error
rather than writing the link to logs.

### 6. Sentry — off unless `SENTRY_DSN` is set

`observability.py` calls `sentry_sdk.init(dsn, traces_sample_rate=0.1)`. Destination is decided
entirely by the DSN's host, so an EU-region Sentry DSN keeps errors in the EU. Error reports
carry stack traces and request context.

### 7. Frontend analytics — off unless `NEXT_PUBLIC_PLAUSIBLE_DOMAIN` is set

`components/Analytics.tsx`. Cookie-free page analytics; `NEXT_PUBLIC_PLAUSIBLE_SRC` points it at
a self-hosted Plausible instead of `plausible.io`.

### 8. Infrastructure

Caddy talks to Let's Encrypt for certificates; `docker compose build/pull` fetches base images.
Neither carries application data.

### Not present

There is **no usage telemetry, no license check, and no phone-home to the ProveKit project** in
the backend, the frontend, or the SDK. A ProveKit host with all of the above unconfigured and
no provider connection makes no outbound application connections at all.

---

## What a self-hoster controls

| Knob | Effect on residency |
|---|---|
| Where you run the host | Decides where 100% of data at rest lives. This is the whole story for storage. |
| `BACKUP_DIR` + off-box copies | Backups are a full second copy. Replicating them to another region moves your data to another region. Be deliberate. |
| Provider connections | Not configured → no provider egress. This is the switch, and it is off by default. |
| `base_url` on an `openai_compatible` connection | Points re-runs at a regional or self-hosted OpenAI-shaped endpoint instead of `api.openai.com`. |
| `mock` provider | Playground and replay work with no network and no key at all. |
| `REDACT_PII=true` | `services/redact.py` masks emails, card numbers and secrets in spans **before storage** — so they are absent from the database, the backups, and anything re-sent to a provider. Best-effort and pattern-based; not a substitute for not logging secrets. |
| `RUNS_RETENTION` | Bounds how long span data exists at all. Deleted data has no residency question. |
| `OTEL_EXPORT_URL`, `SENTRY_DSN`, `SMTP_*`, `NEXT_PUBLIC_PLAUSIBLE_*` unset | Removes items 2, 5, 6 and 7 above entirely. |
| Per-project `replay_url` and `webhook_url` | You choose the destinations. |
| Egress firewall on the host | The only enforcement that doesn't depend on configuration discipline. If residency is a hard requirement, allow-list egress at the network layer rather than trusting a settings page. |

---

## What an EU-resident deployment would require

Achievable today with configuration, for everything except provider calls:

1. **Host in the EU.** Provision the VM in an EU region and follow [DEPLOY.md](DEPLOY.md).
   Postgres, Redis, the spool and the logs are all local to it; there is nothing to shard.
2. **Keep backups in the EU.** `BACKUP_DIR` is on the same host by default, so this is a
   decision only when you ship dumps off-box — send them to EU object storage, and run the
   restore drill against the remote copy ([BACKUP.md](BACKUP.md)).
3. **EU mail provider** for `SMTP_*`, or leave SMTP unset and accept no reset emails.
4. **EU error reporting** — an EU-region Sentry DSN, or no `SENTRY_DSN`.
5. **EU or self-hosted analytics** — `NEXT_PUBLIC_PLAUSIBLE_SRC` at your own instance, or leave
   `NEXT_PUBLIC_PLAUSIBLE_DOMAIN` unset.
6. **EU alert/replay destinations** — `events.eu.pagerduty.com`, `api.eu.opsgenie.com`, your own
   replay endpoint.
7. **Decide the provider question.** This is the only genuinely hard one, and ProveKit cannot
   decide it for you:
   - **Don't re-run.** Ingest, search, compare and score with deterministic scorers never touch a
     provider. Turn the playground off by simply not connecting a provider key. Model-graded
     scoring (`judge`) is the one evaluation feature you lose.
   - **Point re-runs at an endpoint in your region.** Any OpenAI-shaped endpoint works via the
     `openai_compatible` provider and its `base_url` — a regional deployment, a self-hosted open
     model, or a gateway you operate. That is a statement about ProveKit's code, not about any
     vendor's guarantees.
   - **Use a vendor's own residency offering.** OpenAI and Anthropic each publish their own data
     residency and processing terms, and those change; check them directly and get it in your
     contract. ProveKit has no visibility into where a provider processes a request.
8. **Enforce it at the network.** Steps 1–7 are configuration, and configuration drifts. An
   egress allow-list on the host turns the intent into a control.

### What is not built

Be clear-eyed about the gap between the above and a product with a residency *feature*:

- No multi-region deployment, no cross-region replication, no failover.
- No per-workspace or per-tenant region pinning — one instance is one region, always.
- No code-level residency enforcement: nothing rejects a provider connection whose `base_url`
  is outside your region, and nothing labels stored rows with a region.
- No data-processing agreement, no certifications, no audited controls. Self-hosting means you
  are the processor and the controls are yours.
- No EU-hosted ProveKit service. There is no ProveKit-operated instance to be resident *in*;
  the only deployment model is your own.

A named customer needing more than this should get the real thing — region-pinned tenancy and a
contractual residency story — not a configuration checklist. Until then, the honest position is
the one at the top of this page: single-region by construction, and the region is yours.

---

## Related

- [DEPLOY.md](DEPLOY.md) — running the stack, and what hosted mode changes
- [BACKUP.md](BACKUP.md) — the second copy of all of this, and the restore drill
- [ADMIN.md](ADMIN.md) — retention, redaction and the platform console
