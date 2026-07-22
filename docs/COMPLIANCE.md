# Compliance posture

What ProveKit actually does about security and data handling, what a buyer can verify for
themselves, and — at the bottom — the list of things a real audit would ask for that do not
exist.

---

## Read this first

**ProveKit is not SOC 2 certified. There is no Type I report, no Type II report, no
observation period, no auditor, and no ongoing attestation of any kind.**

There is also no ISO 27001, no HIPAA attestation, and no PCI scope. Nothing on this page
should be entered into a vendor questionnaire as a certification, and no phrase here —
including "aligned with", "mapped to", or "consistent with" — is used to suggest one. A SOC 2
report is produced by a licensed CPA firm observing a system over months. That has not
happened, and no document written by the people who wrote the code can substitute for it.

What this page *is*: a description of controls that exist in the source, each one pointing at
the file that implements it, so an evaluator can read the code instead of trusting a claim.
Where a control does not exist, it is listed under [The gap list](#the-gap-list) rather than
softened.

**This is not legal advice.** [DPA.md](DPA.md) is a template that has not been reviewed by a
lawyer and is not executed terms.

---

## The deployment model decides who is responsible

This is the most important fact for a procurement review, and it changes the shape of the
whole conversation.

**ProveKit is software you run.** There is no ProveKit-operated control plane, no
ProveKit-operated storage, and no telemetry back to the project — verified in
[RESIDENCY.md](RESIDENCY.md), which walks every outbound connection in the backend, the
frontend and the SDK. When you `docker compose up`, your traces are in your Postgres, on your
host, in your region.

The consequence, stated plainly because it cuts both ways:

| | Who does it |
|---|---|
| Operates the infrastructure your trace data sits on | **You** |
| Controls access to the database | **You** |
| Holds the encryption keys (`SECRET_KEY`) | **You** |
| Sets retention, redaction, backup and egress policy | **You** |
| Is a data processor for your customers' data | **You** |
| Receives your trace data | **Nobody.** Not the ProveKit project |
| Can be audited under SOC 2 for your traces | **You**, on your own infrastructure |

So the honest answer to "is ProveKit SOC 2 compliant?" is that the question is aimed at the
wrong party. ProveKit is a component inside *your* control environment, like Postgres or
Redis. What a buyer can reasonably ask of a component is: what security properties does it
have, are they verifiable, and where does it fall short. That is what follows.

`provekit.online` is the maintainers' own instance of the same open-source stack. It is not a
managed service, carries no SLA, no support commitment and no processing agreement, and should
not be treated as one — see [SUBPROCESSORS.md](SUBPROCESSORS.md).

---

## Controls that exist

Every row names the file that implements it. The "verify it yourself" column is what an
evaluator can do without taking anyone's word.

### Authentication and credentials

| Control | Where | Verify it yourself |
|---|---|---|
| Passwords stored as PBKDF2-HMAC-SHA256, 200,000 iterations, per-user 16-byte salt | `services/auth.py` — `hash_password` | Read the function; it is 5 lines of stdlib `hashlib` |
| Constant-time password comparison, and a dummy hash burned on unknown accounts so login timing doesn't leak account existence | `services/auth.py` — `verify_password`, `DUMMY_HASH` | Read it |
| Sessions are signed HS256 tokens with a `purpose` claim, so a password-reset token cannot be replayed as a session | `services/auth.py` — `make_token`/`read_token` | Read it |
| Session revocation: tokens carry the user's `token_version`; a password reset bumps it and every outstanding session stops verifying | `services/auth.py`, `routers/auth.py` | Read it |
| Cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in hosted mode | `routers/auth.py` — `_set_cookie`, `services/impersonation.py` | Inspect the `Set-Cookie` header |
| API keys stored as SHA-256 hashes only; the plaintext `pk_…` is shown once at creation and never again | `services/apikey.py` | `select * from api_keys` — there is no plaintext column |
| Provider credentials (OpenAI/Anthropic keys) encrypted at rest with Fernet under a `SECRET_KEY`-derived key, used server-side only, never returned to the browser (the UI sees `…a1b2`) | `services/sealing.py` | Read the column; watch the network tab in Settings |
| Hosted mode refuses to boot without a `SECRET_KEY` of ≥16 chars that isn't a known dev default | `main.py` | Try to start it with a weak key |

### Authorization and tenancy

| Control | Where | Verify it yourself |
|---|---|---|
| Every resource is workspace-scoped and re-checked on read; a project key resolves to exactly one project | `services/workspace.py`, `routers/traces.py` | Try reading another workspace's run id |
| Read-only `viewer` role, enforced by HTTP method at the single point where the workspace is resolved — not in middleware, and not by hiding buttons | `services/roles.py` | The module docstring explains why the middleware version was wrong |
| Unknown role strings degrade to `viewer`, not `member` — a typo cannot grant write access | `routers/projects.py` — `add_member` | Read it |
| Platform superadmin is a separate flag from project roles, bootstrappable only by config | `routers/admin.py`, `services/auth.py` — `is_operator` | See [ADMIN.md](ADMIN.md) |
| Operator "view as tenant" support sessions are **read-only, enforced server-side** by ASGI middleware that refuses every non-safe method, and expire via the token's own `exp` | `services/impersonation.py` | Read the module docstring — it is written as a threat argument |

### Audit trail

| Control | Where | Verify it yourself |
|---|---|---|
| Append-only audit log of privileged changes: superuser grant/revoke, project update/delete, member add/remove, key create/revoke, impersonation start/stop. **Not** currently written: project *create* and ingest-key rotation — the constants exist but nothing emits them | `services/audit.py`, `models.py` — `AuditLog` | `GET /api/admin/audit`, filterable by action and searchable by actor/target |
| Records capture actor id + **snapshotted** actor email, action, target type/id/label, JSON detail, client IP, timestamp | `services/audit.py` — `record()` | Read a row |
| A record outlives its subject — the email and label are copied, not joined, so deleting the user or project does not erase the evidence | `services/audit.py`, `routers/projects.py` — `delete_project` leaves `workspace_id` null deliberately | Delete a test project, then read the audit row |
| Auditing never breaks the audited action; a write failure is logged loudly rather than 500-ing a legitimate revoke | `services/audit.py` | Read the `except` branch |

The deliberate limit, stated because an auditor would find it: **reads are not audited.** There
is no record of who *viewed* a trace. `services/audit.py` says why (a row per page load, needing
its own sampling and retention, would bury the privileged-change events). For a control
environment that requires access logging over customer data, this is a gap — see below.

### Data handling

| Control | Where | Verify it yourself |
|---|---|---|
| Optional PII redaction *before storage* — emails, cards, SSNs, provider keys, phone numbers masked to `[REDACTED_<TYPE>]`, so they are absent from the database, the backups, and anything re-sent to a provider | `services/redact.py`; `REDACT_PII` globally or per project | Turn it on and read the row |
| Redaction quality is **measured, not asserted**: 100% recall and an 18% false-positive rate against a 34-case labelled corpus (17 sensitive, 17 clean), re-run on every CI build | `backend/tests/fixtures/redaction_corpus.json`, `tests/test_redaction_corpus.py`; documented in [TRACING.md](TRACING.md) | `pytest tests/test_redaction_corpus.py` |
| Every masked span records what was touched and how many matches, so an altered output is traceable to the masker | `services/redact.py` — `scrub_run` stamps `result.meta.redaction` | Read a masked span's JSON |
| Payloads truncated at 8,000 chars with a stored/original marker — ProveKit keeps no copy you can't see | `services/otel.py` — `MAX_PAYLOAD_CHARS` | Read a truncated span's `meta.truncation` |
| Server logs are JSON lines with a request id; **traced inputs/outputs are never logged** | `observability.py` | `docker logs` on a busy instance |
| The SDK sends nothing with `PROVEKIT_ENDPOINT` unset — there is no default endpoint | `provekit/trace.py` | Run the SDK with no config and watch the network |

### Network and abuse

| Control | Where | Verify it yourself |
|---|---|---|
| SSRF guard on user-influenced outbound URLs: OTLP re-emit, replay webhooks, alert/outbound webhooks, and `openai_compatible` base URLs (the last of these was unguarded until a review for this document found it): link-local/metadata blocked always, all private/reserved ranges blocked in hosted mode, hostnames DNS-resolved first | `services/netguard.py` | Point a replay webhook at `169.254.169.254` |
| stdio MCP connections (which spawn a local process) refused in hosted mode | `services/netguard.py` — `guard_stdio` | Read it |
| Rate limits on ingest, login, password reset and playground; per-account monthly span quota; monthly provider spend cap returning 402 | `services/limits.py` | Exceed one |
| Ingest durability: each batch is fsynced to disk before it is acknowledged and released only once the rows commit, with a drain task replaying anything left staged | `services/spool.py` | Kill the database mid-ingest |
| Baseline hardening headers (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, HSTS in hosted mode) at the app and again at the proxy | `observability.py`, `Caddyfile` | `curl -I` |
| Share links are stateless HMAC-SHA256 over (workspace, trace, expiry), read-only, one trace, 30-day default TTL | `services/share.py` | Try editing the token |

### Software supply chain and change management

| Control | Where | Verify it yourself |
|---|---|---|
| Every change runs lint (`ruff`), the backend suite with a **95% coverage gate**, TypeScript typecheck, frontend production build, TS client tests, and both Docker image builds | `.github/workflows/ci.yml`, `backend/pyproject.toml` — `fail_under = 95` | Read the workflow; open any PR |
| CI fails on any new high/critical npm advisory | `.github/workflows/ci.yml` — `npm audit --audit-level=high` | Read the workflow |
| Dependabot raises grouped weekly PRs for npm, pip and GitHub Actions, with security updates as they land | `.github/dependabot.yml` | Read it |
| Backend tested across Python 3.11–3.13 | `.github/workflows/ci.yml` | Read it |
| Private vulnerability disclosure with a 72-hour acknowledgement target | [SECURITY.md](../SECURITY.md) | — |
| Backups: nightly `pg_dump` **plus a weekly restore drill** that restores into a throwaway database and fails loudly if the schema or row counts are wrong | [BACKUP.md](BACKUP.md), `deploy/verify-restore.sh` | Run the drill |

That last row is worth pausing on, because it is the one control here that is usually claimed
and rarely true: the restore is exercised on a schedule, not assumed.

---

## Data retention statement

**The mechanism.** ProveKit prunes spans on ingest to a per-project cap: `RUNS_RETENTION`
(default **10,000 spans**) globally, overridable per project in Settings. Deletion is
immediate and hard — the rows are `DELETE`d from Postgres, not flagged
(`routers/traces.py` — `_prune_runs`).

**It is observable.** Every prune adds to an hourly tally in the `retention_events` table
(coalesced by hour, because pruning runs on nearly every batch). `GET /api/workspace/retention`
returns the policy in force, how many spans are stored, `oldest_retained_at`, the total pruned,
and the last 48 hourly buckets. That endpoint exists so "my trace is missing" has an answer
distinguishable from "it never arrived".

**Be precise about what kind of retention this is**, because a contract will not be:

| | |
|---|---|
| Policy shape | **Count-based** — keep the newest N spans per project |
| Policy shape it is **not** | **Time-based.** There is no "delete after 30 days". A quiet project can hold spans indefinitely; a busy one can drop yesterday's inside an hour |
| Scope | Spans (`runs`). Datasets, experiments, prompt versions, saved views, feedback, notes and audit rows are **not** pruned by retention and persist until deleted explicitly |
| Backups | A backup taken before a prune still contains the pruned spans. Retention does not reach into `BACKUP_DIR`. This is the copy people forget |
| Deletion of a whole project | `DELETE /api/projects/{id}` removes runs, feedback, datasets, experiments, alerts, keys and memberships, then the project row. Verify against the handler before relying on this list in a deletion commitment — offloaded payload blobs (`services/payloads.py`) and staged ingest batches are removed on their own schedules, not by this call, and writes an audit record with the span count deleted |
| Deletion of a *user* | **No endpoint exists.** See the gap list |
| Deletion of one subject's data across projects | **No mechanism exists.** See the gap list |

If your commitment to a customer is "their data is deleted within N days", the count-based cap
does not implement it. Today the honest options are to set a small per-project cap, run your
own scheduled `DELETE` against `runs` by `created_at`, or turn on `REDACT_PII` so the sensitive
substance never lands. Time-based retention is a missing feature, not a configuration.

---

## Subprocessors

For a self-hosted deployment the list is **empty by default** — ProveKit makes no outbound
application connection at all until you configure one, and there is no phone-home. Every
possible third party is one you switch on. The full enumeration, including what data each one
would see, is [SUBPROCESSORS.md](SUBPROCESSORS.md).

---

## Data processing agreement

[DPA.md](DPA.md) is a **template**, not executed terms, and has not been through legal review.
Because self-hosting means no data reaches the ProveKit project, the usual controller/processor
DPA has no counterparty on our side. The template is provided for the deployment where *you*
are the processor for *your* customers and need a document to start from.

---

## The gap list

What a SOC 2 Type II audit would ask for that ProveKit does not have. This section exists so a
buyer can assess rather than be reassured; it is deliberately the longest specific section on
the page.

### Audit and attestation

- **No SOC 2 report of any kind**, no auditor engaged, no observation period started, no
  readiness assessment performed.
- **No third-party penetration test.** No external security review has been done on this
  codebase.
- **No ISO 27001, HIPAA BAA, PCI DSS scope, or FedRAMP** anything.
- **No independent verification of anything on this page.** Every claim above is
  self-assessed, which is exactly what an audit exists to replace.

### Organizational controls (the part of SOC 2 that is not code)

A Type II audit is mostly about the organization, and there is very little organization here:

- No written information security policy set, no acceptable-use policy, no formal risk
  assessment, no annual policy review cycle.
- No security awareness training, no background checks, no onboarding/offboarding checklists.
- No documented incident response plan with severity tiers and notification timelines, and no
  incident post-mortem history. (`SECURITY.md` has a disclosure address and a 72-hour
  acknowledgement target. That is a reporting channel, not an IR program.)
- No business continuity or disaster recovery plan beyond the backup and restore drill in
  [BACKUP.md](BACKUP.md).
- No vendor management program, no change advisory board, no formal access reviews.
- No documented separation of duties, and no evidence-collection tooling (Vanta/Drata-style)
  producing a control-by-control trail.

### Technical gaps

- **No Content-Security-Policy.** The other hardening headers ship; script sources are not
  constrained (`observability.py`).
- **Read access is not audited.** Nothing records who viewed a trace, so there is no access
  log over customer data — the control an auditor asks about first.
- **No account deletion and no data-subject erasure.** There is no endpoint to delete a user,
  and no way to find or remove one data subject's content across projects. A GDPR erasure or
  access request has to be answered with SQL.
- **No structured data export for a subject request.** Traces can be read through the API per
  project; there is no "everything about this person" export.
- **No time-based retention**, as above.
- **No encryption at rest for the database as a whole.** Provider credentials are Fernet-sealed
  and passwords/keys are hashed, but *trace content itself is stored in plaintext columns* —
  prompts, model outputs and tool arguments. Disk-level encryption is your infrastructure's job,
  not ProveKit's, and nothing in the app enforces it.
- **No key rotation procedure.** Rotating `SECRET_KEY` invalidates every session and every
  issued share link, and there is no re-sealing path for stored provider credentials.
- **Share links cannot be revoked individually** — the token is stateless, so the only
  invalidation before expiry is rotating `SECRET_KEY`. A `ttl_days <= 0` link never expires.
- **No MFA, no SSO/SAML, no SCIM.** Password login only. Enterprise identity requirements are
  not met.
- **Superuser grants are audited, but a config-bootstrapped operator (`SUPERUSER_EMAILS`)
  cannot be revoked through the API** — only by editing config and restarting.
- **The SSRF guard does not defend against DNS rebinding** without a pinned-egress proxy
  (`services/netguard.py` says so itself).
- Without `REDIS_URL`, rate-limit windows are per-worker, so effective caps scale with worker
  count.
- **Redaction is best-effort regex** with a measured 18% false-positive rate and recall
  measured only over the patterns the corpus covers. It is a safety net, not a guarantee, and
  it is off by default.
- **No formal SBOM** is published, and there is no dependency-signing or provenance
  attestation on the built images.

### If you are being asked for SOC 2 by your own customer

The realistic path, in order:

1. **Self-host.** The data never leaves your control environment, so ProveKit falls inside the
   scope you already have rather than adding a vendor to it. This is the whole argument, and
   for most reviewers it ends the conversation.
2. Point at [SUBPROCESSORS.md](SUBPROCESSORS.md) — a component that adds no subprocessors is
   materially easier to approve than one that adds three.
3. Close the gaps that are *yours*: disk encryption, network egress policy, access reviews on
   the host, and your own retention job if you need a time-based one.
4. Treat this page as a component questionnaire response, and do not represent it as an
   attestation. If a deal requires a SOC 2 report for ProveKit specifically, the accurate
   answer is that one does not exist.

---

## Related

- [SECURITY.md](../SECURITY.md) — threat model, secret handling, disclosure
- [SUBPROCESSORS.md](SUBPROCESSORS.md) — the (near-empty) third-party list
- [DPA.md](DPA.md) — data processing agreement template
- [RESIDENCY.md](RESIDENCY.md) — where data physically lives and every outbound connection
- [BACKUP.md](BACKUP.md) — the nightly dump and the weekly restore drill
- [ADMIN.md](ADMIN.md) — retention, redaction, audit log and the platform console
- [TRACING.md](TRACING.md) — capture, truncation, and measured redaction quality
