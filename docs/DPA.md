# Data Processing Agreement — template

---

> ## ⚠️ THIS IS A TEMPLATE. IT IS NOT AN AGREEMENT.
>
> - **Not executed terms.** Nothing here binds anyone. There are no signatures, no parties, and
>   no offer. Copying this file into a contract folder does not create a DPA.
> - **Not reviewed by a lawyer.** It was written by the people who wrote the software, from the
>   shape of GDPR Article 28, as a starting point. It has had no legal review in any
>   jurisdiction.
> - **Not legal advice**, and not a substitute for counsel. Data protection law varies by
>   jurisdiction and by what you actually do with the data.
> - **Not a DPA with the ProveKit project.** ProveKit is software you run. The project receives
>   no data from your deployment ([SUBPROCESSORS.md](SUBPROCESSORS.md)), so there is no
>   controller/processor relationship to paper over and no counterparty on our side to sign.
> - **It asserts no certification.** ProveKit is not SOC 2 audited or certified under any
>   scheme — see [COMPLIANCE.md](COMPLIANCE.md), including its gap list, before you represent
>   any of Annex II to a customer.
>
> **Who this is for:** you run ProveKit, your customers' personal data flows through the traces
> you capture, and *you* are the processor who needs a document to start from. Take this to
> your lawyer, delete what does not apply, and fill in every `[BRACKETED]` field.
>
> Every `[BRACKETED]` value is a decision you have to make. If you sign it with brackets still
> in it, you have signed something you did not read.

---

## Data Processing Agreement

This Data Processing Agreement ("**DPA**") forms part of the `[MAIN AGREEMENT / TERMS OF
SERVICE]` dated `[DATE]` (the "**Agreement**") between:

- `[CUSTOMER LEGAL ENTITY]`, `[REGISTERED ADDRESS]` (the "**Controller**"); and
- `[YOUR LEGAL ENTITY]`, `[REGISTERED ADDRESS]` (the "**Processor**").

In the event of conflict between this DPA and the Agreement, this DPA prevails in respect of
the processing of Personal Data.

### 1. Definitions

"**Applicable Data Protection Law**" means `[GDPR (EU) 2016/679 / UK GDPR / CCPA / …]`.
"**Personal Data**", "**Processing**", "**Controller**", "**Processor**", "**Data Subject**"
and "**Personal Data Breach**" have the meanings given in Applicable Data Protection Law.
"**Services**" means `[DESCRIPTION OF YOUR SERVICE]`, in which the Processor operates ProveKit,
open-source LLM-observability software, to capture and store execution traces of AI agents.

### 2. Scope and roles

The Controller is the controller of the Personal Data described in Annex I. The Processor
processes that Personal Data only on the Controller's documented instructions, which are
constituted by the Agreement, this DPA, and any further written instruction the Controller
gives.

The Processor shall inform the Controller if, in its opinion, an instruction infringes
Applicable Data Protection Law.

### 3. Subject matter, nature, purpose and duration

Set out in **Annex I**. Processing continues for the term of the Agreement and for the deletion
period in Section 10.

### 4. Confidentiality

The Processor ensures that persons authorised to process the Personal Data are bound by
confidentiality obligations and are granted access on a need-to-know basis. `[DESCRIBE YOUR
ACCESS CONTROL AND CONFIDENTIALITY UNDERTAKINGS — e.g. employment contracts, NDAs, role-based
access on the deployment host.]`

### 5. Security

The Processor implements appropriate technical and organisational measures ("**TOMs**") as set
out in **Annex II**, taking into account the state of the art, the costs of implementation, and
the nature, scope, context and purposes of processing, as well as the risk to Data Subjects.

**The Controller acknowledges that Annex II describes measures partly provided by the ProveKit
software and partly by the Processor's own infrastructure and organisation, and that Annex II
also records measures that are *not* in place.**

### 6. Sub-processors

The Controller gives the Processor `[general / specific]` written authorisation to engage
sub-processors. The current list is in **Annex III**. The Processor shall give the Controller
`[30]` days' notice of any intended addition or replacement, during which the Controller may
object on reasonable data-protection grounds; if the objection cannot be resolved, the
Controller may terminate the affected Services.

The Processor imposes on each sub-processor data-protection obligations no less protective than
this DPA, and remains fully liable to the Controller for its sub-processors' performance.

> **Drafting note.** ProveKit itself adds **no** sub-processors: the software makes no outbound
> application connection until the operator configures one. Annex III is therefore a list of
> *your* infrastructure and of the optional integrations you switched on — most importantly the
> model provider, if you connected one. See [SUBPROCESSORS.md](SUBPROCESSORS.md).

### 7. Data subject rights

Taking into account the nature of the processing, the Processor assists the Controller by
appropriate technical and organisational measures, insofar as possible, in fulfilling the
Controller's obligation to respond to requests to exercise Data Subject rights. The Processor
shall promptly notify the Controller of any request received directly from a Data Subject and
shall not respond to it itself except on the Controller's instruction.

> **Drafting note — read before you commit to a response time.** ProveKit has **no
> data-subject access or erasure feature**. There is no per-subject search, no per-subject
> export, and no account-deletion endpoint. Trace content is free text, so personal data can
> appear anywhere in a prompt or a model output. Answering a request today means querying the
> database directly. Available primitives: delete a whole project
> (`DELETE /api/projects/{id}`, which removes its runs, feedback, datasets, experiments,
> alerts, keys and memberships) and the count-based retention cap. Do not promise a `[30]`-day
> erasure SLA you have not proven you can meet — see the retention statement in
> [COMPLIANCE.md](COMPLIANCE.md).

### 8. Personal Data Breach

The Processor shall notify the Controller without undue delay and in any event within `[24 /
48 / 72]` hours of becoming aware of a Personal Data Breach affecting the Personal Data,
providing the information required under Applicable Data Protection Law to the extent known,
and shall provide reasonable assistance with the Controller's own notification obligations.

`[DESCRIBE YOUR DETECTION AND ESCALATION PATH. If you do not have a documented incident
response plan, write the timeline you can actually meet, not the one that sounds best.]`

### 9. Assistance, DPIAs and audits

The Processor provides reasonable assistance with data protection impact assessments and prior
consultations. The Processor makes available information necessary to demonstrate compliance
with Article 28 and allows for and contributes to audits, including inspections, conducted by
the Controller or an auditor it mandates, on `[30]` days' notice, no more than `[once]` per
year except following a Personal Data Breach.

> **Drafting note.** There is no third-party audit report to offer in lieu of an inspection.
> ProveKit has no SOC 2 report and no penetration test ([COMPLIANCE.md](COMPLIANCE.md)). If you
> intend to satisfy audit rights with a report, it will have to be one you commission.

### 10. Deletion and return

On termination of the Agreement, and at the Controller's election, the Processor shall delete
or return all Personal Data and delete existing copies within `[30]` days, unless retention is
required by law.

> **Drafting note.** "Delete existing copies" includes **backups**. ProveKit's retention
> pruning does not reach into `BACKUP_DIR`, and a dump taken before a deletion still contains
> the data ([BACKUP.md](BACKUP.md)). Either shorten your backup rotation to under the deletion
> window, or state a backup-expiry carve-out here honestly rather than signing a commitment
> your backups break.

### 11. International transfers

The Processor shall not transfer Personal Data outside `[EEA / UK / …]` without a valid transfer
mechanism (Standard Contractual Clauses, adequacy decision, or equivalent).

> **Drafting note.** Where the data sits is decided entirely by where you run the container —
> ProveKit is single-region by construction, with no cross-region replication and no code-level
> residency enforcement. The transfer that catches people out is the **model provider call**,
> which sends full prompt content and happens only on re-runs. [RESIDENCY.md](RESIDENCY.md)
> covers both, including how to run with no provider connection at all.

### 12. Liability, term and governing law

`[AS PER THE MAIN AGREEMENT — or set out here.]` This DPA is governed by `[GOVERNING LAW]` and
takes effect on `[DATE]`, continuing for as long as the Processor processes Personal Data on
the Controller's behalf.

**Signed:**

| Controller | Processor |
|---|---|
| Name: `[ ]` | Name: `[ ]` |
| Title: `[ ]` | Title: `[ ]` |
| Date: `[ ]` | Date: `[ ]` |

---

## Annex I — Description of the processing

| | |
|---|---|
| **Subject matter** | Capture, storage and analysis of AI-agent execution traces on the Processor's infrastructure |
| **Duration** | The term of the Agreement, plus the deletion period in Section 10 |
| **Nature and purpose** | Debugging, evaluation, quality monitoring and cost analysis of AI agent behaviour |
| **Categories of Data Subjects** | `[e.g. the Controller's end users whose inputs reach the agent; the Controller's employees who use the portal]` |
| **Categories of Personal Data** | **Portal accounts:** email address, name, PBKDF2 password hash, role assignments, IP address in audit records. **Trace content:** free text. Whatever the Controller's agent passed through — prompts, model outputs, tool arguments — which may contain personal data of any category. `[NARROW THIS TO WHAT YOUR AGENT ACTUALLY HANDLES.]` |
| **Special categories** | `[NONE / SPECIFY.]` Trace content is unstructured, so this is a statement about what your agent handles, not something the software can enforce |
| **Frequency** | Continuous, on ingest |
| **Retention** | `[STATE YOUR POLICY.]` The software's mechanism is a **count-based** cap — newest N spans per project, default 10,000 — not a time-based one. See [COMPLIANCE.md](COMPLIANCE.md) |

## Annex II — Technical and organisational measures

**Fill this in honestly.** Everything below marked *(software)* is implemented in ProveKit and
verifiable in the source; everything marked *(yours)* is the Processor's own responsibility and
is **not** provided by ProveKit.

| Measure | Status |
|---|---|
| Password storage: PBKDF2-HMAC-SHA256, 200,000 iterations, per-user salt | *(software)* `services/auth.py` |
| API keys stored as SHA-256 hashes; plaintext shown once | *(software)* `services/apikey.py` |
| Provider credentials encrypted at rest (Fernet), never returned to the browser | *(software)* `services/sealing.py` |
| Signed, purpose-scoped session tokens; password reset revokes all sessions | *(software)* `services/auth.py` |
| Role-based access control incl. a read-only viewer role, enforced server-side | *(software)* `services/roles.py` |
| Workspace isolation re-checked on every read | *(software)* `services/workspace.py` |
| Append-only audit log of privileged changes (actor, action, target, IP, timestamp) | *(software)* `services/audit.py` |
| Operator support sessions are read-only and audited | *(software)* `services/impersonation.py` |
| Optional PII masking before storage, with measured recall/false-positive rates | *(software)* `services/redact.py`; **off by default — turn it on** |
| SSRF protection on user-supplied outbound URLs (`services/netguard.py`); link-local/metadata refused in every mode, private ranges additionally refused in hosted mode | *(software)* `services/netguard.py` |
| Rate limits, per-account quotas and a provider spend cap | *(software)* `services/limits.py` |
| Ingest durability (fsync-before-ack spool with replay) | *(software)* `services/spool.py` |
| Security headers incl. HSTS in hosted mode | *(software)* `observability.py` + `Caddyfile` |
| CI: lint, 95% coverage gate, typecheck, dependency advisory gate, Dependabot | *(software)* `.github/` |
| **Encryption in transit (TLS)** | *(yours)* — bundled Caddy config provisions Let's Encrypt certificates; you operate it |
| **Encryption at rest for the database volume** | *(yours)* — **trace content is stored in plaintext columns.** Disk/volume encryption is your infrastructure's job |
| **Backups and tested restore** | *(yours)*, tooling provided — nightly dump + weekly restore drill ([BACKUP.md](BACKUP.md)). Say whether you run them |
| **Physical security, network segmentation, egress control** | *(yours)* |
| **Access reviews, onboarding/offboarding, background checks, security training** | *(yours)* |
| **Documented incident response plan** | *(yours)* |
| **Business continuity / disaster recovery plan** | *(yours)* |
| **MFA / SSO on portal accounts** | **Not available.** ProveKit supports password login only |
| **Audit logging of data *reads*** | **Not available.** Privileged changes are logged; who viewed a trace is not |
| **Content-Security-Policy** | **Not implemented** |
| **Time-based retention / per-subject erasure** | **Not implemented** — see Section 7 |
| **SOC 2 / ISO 27001 / penetration test** | **None.** See the gap list in [COMPLIANCE.md](COMPLIANCE.md) |

Do not delete the "Not available" rows to make the annex look better. They are the rows a
regulator reads.

## Annex III — Sub-processors

ProveKit contributes **no** sub-processors. List yours.

| Sub-processor | Purpose | Location | Personal Data it receives |
|---|---|---|---|
| `[HOSTING PROVIDER]` | Compute and storage for the deployment | `[REGION]` | All data at rest |
| `[MODEL PROVIDER, if you connected one]` | Trace re-runs, playground, model-graded scoring | `[REGION]` | **Full prompt and completion content**, on re-runs only |
| `[EMAIL PROVIDER, if SMTP configured]` | Transactional email | `[REGION]` | Recipient address, reset/verification links |
| `[ERROR REPORTING, if SENTRY_DSN set]` | Error monitoring | `[REGION]` | Stack traces, request context |
| `[ANALYTICS, if configured]` | Page analytics | `[REGION]` | Cookie-free page views |
| `[BACKUP STORAGE, if off-box]` | Backups | `[REGION]` | A full copy of the database |

Delete every row you did not switch on. If you switched none on, the table is empty — and that
is the accurate answer, not an omission.

---

## Related

- [COMPLIANCE.md](COMPLIANCE.md) — posture, controls, retention statement, and the gap list
- [SUBPROCESSORS.md](SUBPROCESSORS.md) — what each optional integration would receive
- [RESIDENCY.md](RESIDENCY.md) — where data lives and every outbound connection
- [BACKUP.md](BACKUP.md) — backups, and why they matter to a deletion clause
