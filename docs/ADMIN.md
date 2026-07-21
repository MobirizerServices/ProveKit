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

All four require a superuser session cookie.

| Endpoint | Returns |
|---|---|
| `GET /api/admin/stats` | the seven deployment-wide counters |
| `GET /api/admin/users` | one page of users, with `project_count` and effective `is_superuser` |
| `GET /api/admin/projects` | one page of projects, with owner, member/span counts, retention, `redact_pii` |
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

- **A superuser sees every user's email and every project on the deployment.** They don't get
  project data (traces, keys) through this console, but they can read the DB behind it. Grant it
  the way you'd grant production database access.
- **There is no audit trail.** Grants and revocations aren't recorded — no log of who promoted
  whom or when. If you need that, capture it outside ProveKit for now.
- **Search is a substring match, not an index.** `q` runs a `LIKE` over email/name, which is
  fine at thousands of rows and will need an index well before millions.
- **`SUPERUSER_EMAILS` grants on email match alone.** On a deployment where anyone can sign up,
  a listed address is a standing claim on operator access — combine it with
  `REQUIRE_EMAIL_VERIFICATION=true` so an unverified signup can't claim a listed address.

See also: [Security](../SECURITY.md) for the threat model, and
[Deployment](DEPLOY.md) for the surrounding configuration.
