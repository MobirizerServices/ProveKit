# Admin console (platform operators)

A deployment-wide operator view at **`/admin`**: how many users, projects, and spans this
instance holds, who the users are, and which projects exist. It's for whoever *runs* the
deployment — not for project owners.

```
  /settings   →  one project you're a member of  (name, members, retention, PII, connections)
  /admin      →  every user and every project on this deployment
```

Superuser is a **platform-operator credential, separate from project roles**. An owner of a
project is not an admin; an admin is not automatically a member of any project.

> **Self-hosting only.** On a single-tenant instance you are the operator. This page matters most
> when you run ProveKit for other people.

## Who gets in

A request passes `require_superuser` if **either** is true:

1. the user's **`is_superuser` flag** is set in the database, **or**
2. the user's email appears in the **`SUPERUSER_EMAILS`** config (a comma-separated list).

The check is an `or`, which has a consequence worth reading twice — see
[Revoking](#revoking-actually-revoking) below.

Everyone else gets `403`. The **Admin** link only appears in the nav for superusers (the
`is_superuser` field on `GET /api/auth/me`), and the page renders "You don't have access to the
admin console." if you reach it directly.

## Bootstrapping the first operator

There's a chicken-and-egg problem — no one can grant the first flag. `SUPERUSER_EMAILS` is the
way in:

1. Set it in the backend environment (e.g. in `.env` or your compose file):

   ```bash
   SUPERUSER_EMAILS=you@yourco.com
   ```

2. Restart the backend. Settings are read once and cached (`@lru_cache`), so a running process
   won't pick up the change.
3. Sign in with **that exact email** (case-insensitive). The account must already exist — the
   list grants privileges to an account, it doesn't create one. Sign up first if needed.
4. Open **/admin**.

Then move off the bootstrap: while your address is listed, your own row shows
**✓ Superuser · config** with no toggle, so set `users.is_superuser = true` directly in the
database (or have a second operator **Grant** it to you), then drop the address from
`SUPERUSER_EMAILS` and restart. Operators held in the database can be granted and revoked
without a deploy; operators held in config cannot.

For provekit.online this is `SUPERUSER_EMAILS=info@provekit.online` — see
[DEPLOY_PROVEKIT_ONLINE.md](DEPLOY_PROVEKIT_ONLINE.md).

### Local development

Local (non-hosted) mode has no login: every request resolves to an auto-created user with the
fixed email **`local@provekit`**. To see the console while developing:

```bash
SUPERUSER_EMAILS=local@provekit
```

## What the console shows

**Counters** — users · projects · members · traces · spans · datasets · experiments, across the
whole deployment. ("Traces" counts root spans; "spans" counts every captured row, so spans is
always the larger number.)

**Users table** — email, name, auth provider, how many projects they belong to, and a
**Grant / ✓ Superuser** toggle.

**Projects table** — name, owner email, member count, span count, and the project's
**retention** and **PII masking** overrides (`default` / `—` when unset, meaning it inherits the
global `RUNS_RETENTION` / `REDACT_PII`).

The projects table is the fastest way to answer "who is filling the database?" — sort by span
count and check whether that project has a retention override.

## API

All of these require a superuser session cookie (see also
[Impersonation](#impersonation--read-only-view-as-tenant) below).

| Endpoint | Returns |
|---|---|
| `GET /api/admin/stats` | the seven deployment-wide counters |
| `GET /api/admin/users` | one page of users, with `project_count` and effective `is_superuser` |
| `GET /api/admin/projects` | one page of projects, with owner, member/span counts, retention, `redact_pii` |
| `GET /api/admin/audit` | one page of audit entries; `action=` filters exactly, `q=` matches actor or target |
| `PATCH /api/admin/users/{id}` | `{"is_superuser": true｜false}` — grant or revoke the DB flag; `409` if the target is granted by `SUPERUSER_EMAILS`, `400` on self-revoke |

`GET /api/admin/users` returns both `is_superuser` (the effective answer, flag **or** config) and
`is_bootstrap` (true when config is the source) so a client can tell the two apart.

Both list endpoints are **paged and searchable**, and return the rows beside the totals:

```jsonc
// GET /api/admin/users?limit=50&offset=0&q=acme
{ "total": 128, "limit": 50, "offset": 0, "users": [ /* … */ ] }
```

`limit` defaults to 50 and is capped at 200; `offset` pages through. `q` matches email or name
for users, and project name or owner email for projects — `total` is the size of the whole
match, not of the page, so it drives the pager. The console hides its pager entirely when
everything fits on one page.

## Impersonation — read-only "view as tenant"

Most support tickets are "my traces aren't showing up". Asking the customer for screenshots turns
a five-minute answer into a day. An operator can instead open a **time-boxed, read-only view of
one project**:

```bash
curl -X POST /api/admin/impersonate -b cookies \
  -d '{"workspace_id": 42, "reason": "ticket 4412: missing traces", "minutes": 15}'
curl /api/admin/impersonate/traces -b cookies        # what that project sees at /traces
curl -X DELETE /api/admin/impersonate -b cookies     # stop
```

Five properties, in the order they matter:

1. **Read only, enforced on the server.** While the session is impersonating, *every* request
   that isn't `GET`/`HEAD`/`OPTIONS` is refused with `403 … read-only`, anywhere in the API —
   not just in the pages the console hides. The single exception is `DELETE
   /api/admin/impersonate`, because the way out must never be blocked. The check is by method,
   so a mutating endpoint written next year is covered the day it is written.
2. **Audited at both ends.** `impersonation.start` and `impersonation.stop` land in the audit
   trail with the operator's email, the target project, the caller's IP, and the **reason** —
   which the API requires, so the trail answers *why* and not only *who*.
3. **Time-bounded by the signature.** The deadline is the session token's own `exp` (default 15
   minutes, max 60), so an expired support session is not a session at all — there is nothing
   left to replay. When it lapses, the operator is simply signed out and logs back in.
4. **No escalation.** Impersonating does not grant the tenant's privileges *or* keep the
   operator's: the rest of `/api/admin` (stats, users, grants) returns `403` while a support
   session is open. Start one, look, stop, then act.
5. **No cross-tenant reach.** Project resolution (`X-Project-Id` → membership check) never looks
   at the impersonation claim, so the ordinary APIs keep returning the *operator's* own project
   mid-session. The tenant's data is reachable only through `/api/admin/impersonate/*`.

Mechanically, the claim rides inside the normal signed session cookie as one extra field. There
is deliberately no second credential: two ways to be authenticated is how one of them ends up
unguarded.

| Endpoint | Does |
|---|---|
| `POST /api/admin/impersonate` | start; `{"workspace_id", "reason", "minutes"}` (`reason` required, `minutes` 1–60, default 15). `404` unknown project, `422` bad duration/reason, `403` if already impersonating |
| `GET /api/admin/impersonate` | the banner: `{"active": false}` or project, owner, `seconds_remaining` |
| `DELETE /api/admin/impersonate` | stop, restore the operator's own session, audit it |
| `GET /api/admin/impersonate/traces` | the tenant's trace list — the same query `/api/traces` runs for them (`limit`, `status`, `window_hours`, `q`, `cursor`) |
| `GET /api/admin/impersonate/traces/{trace_id}` | all spans of one of their traces |

> **Deployment note.** The read-only guarantee is the `ReadOnlyImpersonation` ASGI middleware
> (`services/impersonation.py`), registered in `main.py`. If it is ever removed, an impersonating
> operator can still write — as *themselves*, in *their own* project, never the tenant's — so the
> tenant-safety property survives, but the "support mode is read-only" promise does not. Keep it
> registered.

## Revoking

How you revoke depends on **where the grant came from**, because config wins over the flag:

| Granted by | Revoke with | Restart needed |
|---|---|---|
| the `is_superuser` flag (the **Grant** button) | click **✓ Superuser** to toggle it off | no |
| `SUPERUSER_EMAILS` | remove the address from the config | **yes** |

A config-granted account shows as **✓ Superuser · config** in the users table rather than a
toggle, because clearing the flag can't revoke it — the gate is
`is_superuser OR email in SUPERUSER_EMAILS`. Attempting it through the API is refused with a
`409` naming the config, rather than returning `200` for a change that would have no effect.

This is why moving operators off `SUPERUSER_EMAILS` and onto the database flag is worth doing:
flag changes take effect immediately, config changes need a deploy.

**You cannot revoke your own access** (`400 You can't remove your own superuser access`). This
prevents locking the deployment out of its own console, but it means removing an operator
requires a *second* operator — or direct database access.

## Cautions

- **A superuser sees every user's email and every project on the deployment**, and can open a
  read-only view of any project's traces (above). Keys are never exposed, and the read is
  audited — but they can read the database behind all of it regardless. Grant superuser the way
  you'd grant production database access.
- **Impersonation is recorded, not prevented.** The audit trail is what makes it accountable, so
  it is only as good as your ability to read it: `GET /api/admin/audit?action=impersonation.start`
  is the query to put in front of whoever reviews support access.
- **The audit trail covers changes, not reads.** Grants, revocations, project deletion and
  settings, membership, and key lifecycle are recorded with actor, target, IP and timestamp.
  *Who viewed a trace* is not — that would write a row per page load and bury the privileged
  events. Records are append-only from the app's side (there is no delete endpoint), but a
  superuser with database access can still edit the table; ship logs off-box if you need
  tamper-evidence.
- **Search is a substring match, not an index.** `q` runs a `LIKE` over email/name, which is
  fine at thousands of rows and will need an index well before millions.
- **`SUPERUSER_EMAILS` grants on email match alone.** On a deployment where anyone can sign up,
  a listed address is a standing claim on operator access — combine it with
  `REQUIRE_EMAIL_VERIFICATION=true` so an unverified signup can't claim a listed address.

See also: [Security](../SECURITY.md) for the threat model, and
[Deployment](DEPLOY.md) for the surrounding configuration.
