# Subprocessors

Third parties that could process data from a ProveKit deployment, and exactly what each one
would see.

Companion to [COMPLIANCE.md](COMPLIANCE.md), which states the posture, and
[RESIDENCY.md](RESIDENCY.md), which walks every outbound connection in the source.

---

## The list, for a self-hosted deployment

**Empty.**

Not "minimal", not "we only use a few" — a ProveKit instance you deploy yourself, with nothing
configured beyond the database, transmits application data to nobody. There is no ProveKit
control plane to receive it, no usage telemetry, no license check and no phone-home in the
backend, the frontend or the SDK. The stack in `compose.prod.yml` is one host running Caddy,
Next.js, FastAPI, Postgres and Redis; your traces are written to a volume on that host and read
back from it.

That is the genuine selling point of this page. Adding an observability tool usually means
adding a vendor to your subprocessor disclosure and re-opening a security review. This one adds
zero, because the software runs inside the boundary you already have.

**ProveKit the project is not a subprocessor of your data**, because it never receives any.

---

## Third parties *you* may switch on

Every entry below is off unless you configure it. Adding any of them makes it your
subprocessor, disclosable by you, on terms you negotiate — ProveKit has no contract with these
vendors on your behalf and makes no representation about them.

| Enabled by | Vendor | What it would receive | Default |
|---|---|---|---|
| Connecting a model provider in Settings | OpenAI, Anthropic, or any `openai_compatible` endpoint you point at | **The full `messages` array** — system prompt, user content, assistant turns — plus model and parameters. This is your prompt content, and it is the highest-sensitivity flow on the page | **Off.** No connection → zero provider calls |
| `SMTP_HOST`, `SMTP_USER`, … | Your mail provider | Recipient addresses; password-reset and verification links | **Off.** Without SMTP, hosted mode refuses to send |
| `SENTRY_DSN` | Sentry (or a self-hosted Sentry) | Stack traces and request context on errors. Destination is decided entirely by the DSN's host | **Off** |
| `NEXT_PUBLIC_PLAUSIBLE_DOMAIN` | Plausible (or your own instance via `NEXT_PUBLIC_PLAUSIBLE_SRC`) | Cookie-free page analytics. No trace content | **Off** |
| `OTEL_EXPORT_URL` | Your downstream collector | Span **metadata only**: name, operation type, provider, model, token counts, status. **No inputs or outputs** (`services/otel.py`) | **Off** |
| A project alert webhook | Slack, Discord, PagerDuty, Opsgenie | The breach message: metric, value, comparator, threshold, window, project name. **No trace content** | **Off** |
| A project `replay_url` | **Your own endpoint** | `{origin_trace_id, fork_span_id, overrides}`. `overrides` is prompt content you chose to change. The destination is yours, so this is usually not a third party at all | **Off** |
| Wherever you run it | Your cloud/VPS provider | Everything at rest: the Postgres volume, the spool directory, backups, logs | Whatever you provisioned |
| Off-box backup copies | Your object storage | A full copy of the database. See [BACKUP.md](BACKUP.md) — this is the copy people forget when they reason about vendors | **Off.** `BACKUP_DIR` is local by default |

Two flows deserve emphasis rather than a table row.

**The provider call is the only one that carries your prompt substance, and it happens only on
re-runs.** Ingesting a trace never calls a provider. The paths that do are the playground,
`services/replay.py`, experiments, and `llm_client.judge()` for model-graded scoring. An
instance where nobody has connected a provider key raises `missing API key for this connection`
rather than falling back to anything — the switch is off, and it is off by default. If your
review cannot accept a provider subprocessor, you can run ProveKit for ingest, search, compare
and deterministic scoring with no provider connection at all; the one feature you lose is
model-graded scoring.

**Your agent already calls the provider.** ProveKit observing it adds no egress. Re-running a
trace in the portal is a *new* call, from the ProveKit host, on data now at rest in your
database — that is the asymmetry worth putting in front of a reviewer.

---

## Infrastructure that carries no application data

Listed for completeness, because a thorough reviewer will ask what the host talks to:

- **Let's Encrypt** — Caddy provisions the TLS certificate for your domain. Sees the domain, not
  your data.
- **Container registries and package indexes** — Docker Hub, PyPI, npm at build/pull time. Base
  images and dependencies in; nothing out.

Neither is a data subprocessor.

---

## `provekit.online`

The maintainers run one instance of the same open-source stack at `provekit.online`.

Be clear about what it is: a demonstration deployment, **not a managed service**. It carries no
SLA, no support commitment, no processing agreement and no uptime or durability guarantee, and
it is not covered by any of the controls in [COMPLIANCE.md](COMPLIANCE.md) as a *service* —
those describe the software, which you should run yourself. Do not put production or
customer-identifying data into it.

For anyone evaluating that instance rather than their own, its configuration
(`deploy/provekit.online.env.example`) means the vendors involved are the VPS provider it runs
on, Titan/BigRock for transactional email (`smtp.titan.email`), and Let's Encrypt for TLS. If
you need any commitment about data handling, self-host — that is the supported model, and the
list above goes back to empty.

---

## Changes to this list

Because a self-hosted deployment has no ProveKit-side subprocessors, there is nothing for the
project to notify you about: the list changes only when *you* configure something. If the
software ever gains a default outbound connection, that is a change to
[RESIDENCY.md](RESIDENCY.md) and this page, and it would be a breaking change in the sense that
matters — call it out in review.

---

## Related

- [COMPLIANCE.md](COMPLIANCE.md) — posture, controls, and the gap list
- [RESIDENCY.md](RESIDENCY.md) — every outbound connection, verified against the source
- [DPA.md](DPA.md) — processing agreement template
- [BACKUP.md](BACKUP.md) — the second copy of everything
