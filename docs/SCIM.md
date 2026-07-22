# SCIM 2.0 provisioning (deprovisioning, mostly)

Removing someone who has left is manual today: an owner opens every project and deletes the
membership, and nothing tells them when they forgot one. SCIM lets the identity provider that
already knows the person has left do it — the moment it happens.

The endpoints live at **`/scim/v2`** (`routers/scim.py`, `services/scim.py`). The create path
exists because a connector needs it; the revoke path is the reason the feature exists, so read
[What `active: false` actually does](#what-active-false-actually-does) even if you skip the
rest.

> **Status: not yet reachable.** The router is written and tested but is **not registered** in
> `provekit/main.py`. Until the line below lands, `/scim/v2/...` returns 404. Nothing in this
> document describes behaviour that is not in the code — but the HTTP surface is not live yet,
> and the HTTP tests in `backend/tests/test_scim.py` skip with exactly that reason rather than
> passing against a router they mounted themselves. (The surface *was* exercised end to end
> against the real app with the line applied in-process, so the wiring is a one-liner and not a
> discovery exercise; those tests un-skip on their own once it lands.)
>
> ```python
> # provekit/main.py — add `scim` to the routers import, then:
> app.include_router(scim.router)
> ```

---

## The credential

**SCIM authenticates with a tenant SCIM token. It is not a project API key.**

A `pk_` key is minted by any project member, lives in CI and `.env` files, and is scoped to
shipping traces. Provisioning can delete people. Sharing one credential between those two blast
radii would mean a key leaked out of a build log could deprovision a company. So SCIM has its
own credential and its own resolution path: `services/scim.authenticate` never calls
`services/workspace.workspace_from_key` or `services/apikey.resolve_workspace`, and a `pk_` key
or an ingest key presented to `/scim/v2` is simply an unknown token (401).

Configure it in the backend environment, one `project id : token` pair per tenant the IdP
provisions:

```bash
# One project, one IdP:
PROVEKIT_SCIM_TOKENS=7:$(python -c "import secrets; print(secrets.token_urlsafe(48))")

# Several tenants on one instance, comma-separated:
PROVEKIT_SCIM_TOKENS="7:9f3c…,12:be21…"
```

* **Unset → SCIM is off.** Every request is a 401 that names the variable.
* **Scope.** A token reaches exactly one project: its members, and nothing else on the
  instance. It cannot read traces, cannot touch another project, and is not a superuser
  credential (that is `SUPERUSER_EMAILS` — see [ADMIN.md](ADMIN.md)).
* **Rotation.** Change the value and restart. The setting is read per request, not cached at
  import, so a restarted worker never serves an old token from an `lru_cache`.
* **Where it lives.** In the process environment, like `SECRET_KEY`. It is **not** hashed at
  rest the way `pk_` keys are, because it is not stored at rest — there is no database row for
  it. That also means there is no in-app "revoke this token" button: revocation is an
  environment change plus a restart.

It is deliberately configured out of band rather than as a field in `config.py`, because this
change was not permitted to touch that file. That is the visible cost: it is the only backend
setting that is not a field on the `Settings` model, so it is absent from the one place someone
goes to read what this deployment can be configured with. Moving it there is a two-line change.

---

## What `active: false` actually does

A session in ProveKit is a signed cookie (`services/auth.py`), not a database lookup. So a
deactivation that only marks a row leaves the leaver's already-open browser tab working for up
to 30 days. `PATCH /scim/v2/Users/{id}` with `active: false` therefore does three things:

1. **Deletes the `WorkspaceMember` row.** Every tenant-scoped route resolves access through
   `services/workspace.current_workspace` → `is_member()`. With the row gone, an
   `X-Project-Id` header naming this project no longer resolves to it.
2. **Bumps `User.token_version`.** This is the one that makes it immediate.
   `services/auth.get_current_user` compares the cookie's `v` claim against this column and
   rejects the cookie the instant the number moves — so every issued session, every unused
   password-reset link and every verify link dies at once, with no wait for expiry.
3. **Clears `User.password_hash`** — but only if the account has no membership left anywhere
   (see [Multiple projects](#multiple-projects)). `routers/auth.login` returns 401 on an empty
   hash, and `routers/auth.forgot` refuses to email a reset link for one, so the account cannot
   be re-entered or self-recovered.

`DELETE /scim/v2/Users/{id}` does exactly the same revocation and additionally stops the account
being visible to this tenant's SCIM at all (a following `GET` is a 404), which is what a
connector expects after a delete.

### What it does *not* do

Stated plainly, because a deprovisioning doc that omits its gaps is worse than none:

* **Project API keys survive.** `ApiKey` rows belong to a project, not a person — there is no
  `user_id` on them — so ProveKit cannot tell which ones a departing employee copied. A key
  they still hold keeps working for ingest and key-authed reads. **Rotate the project's keys in
  Settings → API keys as part of offboarding.** This is the largest remaining hole.
* **Share links survive, and cannot be revoked individually.** `services/share.py` mints
  stateless HMAC-signed tokens — nothing is stored, so there is no list of issued links and no
  per-link or per-user revocation. A link the leaver saved keeps working until its embedded
  expiry (30 days by default; `ttl_days <= 0` mints a link that never expires). The only global
  kill switch is rotating `SECRET_KEY`, which also signs every user out.
* **Platform superuser is not touched.** `is_superuser` and `SUPERUSER_EMAILS` are
  deployment-level; a tenant's IdP does not get to change them. A deprovisioned operator cannot
  sign in (steps 2 and 3 above), but the flag remains set.
* **No rate limiting.** `services/limits.py` is not applied to `/scim/v2`; the bearer token is
  the only gate.
* **The last owner is refused.** Deprovisioning the only owner of a project would leave nobody
  able to manage its members or keys, with no way back in-app, so it returns 400 with
  `scimType: mutability` — the same rule `routers/projects.py` enforces. Transfer ownership
  first (add a second owner via `PATCH /Groups/{id}:owner`), then retry.

---

## Representing "deactivated" with no schema change

There is no `active` column on `User` and this change adds no migration, so the state is
encoded in **`User.auth_provider`** (`String(32)`, previously one of `password | github |
local`):

| `auth_provider`  | Meaning                                                                 |
|------------------|-------------------------------------------------------------------------|
| `password`       | normal account                                                          |
| `scim_off:<pid>` | deprovisioned by project `<pid>`; still listed there as `active: false` |
| `scim_off`       | deleted via `DELETE /Users/{id}`; invisible to every tenant             |

Whether a user is *active for a tenant* is not read from that column, though — it is simply
whether a `WorkspaceMember` row exists. The marker exists for one job: keeping a
just-deactivated user **visible** to the tenant that deactivated them, so the connector's
read-back finds them reporting `active: false` instead of a 404 it logs as a sync failure.

### What this costs

* **`auth_provider` stops recording how the account authenticated.** For a deprovisioned
  account the original value is overwritten and cannot be recovered. Today that loses little
  (only `password` and `local` are ever set — GitHub OAuth is not implemented), but it is a
  real loss the moment a second provider ships, and it shows up as `scim_off:7` in the admin
  console's provider column.
* **A reactivated account comes back as `password`.** There is nowhere to have stored the
  original.
* **The previous role is not remembered.** Deactivate → reactivate restores `member`, not
  whatever they had. Push the group again to restore the real role.
* **No `deactivated_at`.** There is no `updated_at` column either, so SCIM `meta.lastModified`
  repeats `meta.created`. **Delta imports will not see changes made here** — configure the
  connector to do full imports. When a deactivation happened is recoverable only from the audit
  trail (below).
* **One project id fits in the marker.** See below.

### Multiple projects

The SCIM token is scoped to one project, but `token_version` and `password_hash` are
account-level columns. So:

* Bumping the token version **signs the person out of every project they belong to.** They sign
  back in and simply no longer see yours. There is no per-project session revocation without a
  schema change; signing everyone's other sessions out is the conservative direction to be
  wrong in.
* The password is **only** cleared, and the marker only set, once no membership remains
  anywhere. Locking someone out of a second tenant they still legitimately belong to is not
  your tenant's decision.
* A consequence: if the person is still a member elsewhere, your `GET /Users/{id}` returns
  **404** afterwards rather than `active: false` — they are genuinely gone from your project,
  and there is no marker recording that you were the one who removed them. Connectors treat a
  404 as deprovisioned, so this is safe, just less informative.

---

## Endpoints

All responses are `application/scim+json`; all rejections are
`urn:ietf:params:scim:api:messages:2.0:Error` resources with a `scimType` where SCIM defines
one.

| Method   | Path                          | Notes                                              |
|----------|-------------------------------|----------------------------------------------------|
| `GET`    | `/scim/v2/ServiceProviderConfig` | Advertises only what is built: patch + filter yes; bulk, sort, etag, changePassword no |
| `GET`    | `/scim/v2/Users`              | `?filter=userName eq "a@b.com"`, `?startIndex=` (1-based), `?count=` (max 200) |
| `POST`   | `/scim/v2/Users`              | 201. Existing member → 409 `uniqueness`             |
| `GET`    | `/scim/v2/Users/{id}`         | Includes deprovisioned users as `active: false`     |
| `PUT`    | `/scim/v2/Users/{id}`         | Replace. An **omitted** `active` means active       |
| `PATCH`  | `/scim/v2/Users/{id}`         | `active`, `userName`, `displayName`, `name.*`       |
| `DELETE` | `/scim/v2/Users/{id}`         | 204. Full revocation, and forgotten by this tenant  |
| `GET`    | `/scim/v2/Groups`             | Exactly three: `owner`, `member`, `viewer`          |
| `GET`    | `/scim/v2/Groups/{pid}:{role}`| e.g. `7:member`                                     |
| `PATCH`  | `/scim/v2/Groups/{pid}:{role}`| `add` / `remove` on `members`                       |

### The call that matters

```bash
curl -X PATCH https://provekit.example.com/scim/v2/Users/42 \
  -H "Authorization: Bearer $PROVEKIT_SCIM_TOKEN" \
  -H "Content-Type: application/scim+json" \
  -d '{"schemas":["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
       "Operations":[{"op":"replace","path":"active","value":false}]}'
```

Entra ID's path-less form — `{"op":"replace","value":{"active":false}}` — is accepted too, as
is `{"op":"remove","path":"active"}`.

### Filtering

Only `userName eq "…"` (and its `emails.value` spelling). It is the existence probe every
connector runs before a create, and it is the only one this data model can answer. Anything
else is a 400 with `scimType: invalidFilter` rather than a silent match-everything — a filter
that quietly returns all users reads to the IdP as "that person does not exist here", and the
next thing it does is create a duplicate.

`externalId` is **not stored** (no column) and cannot be filtered on or echoed back. Match on
`userName`.

### What is persisted

`userName` (the email, lowercased), `displayName` / `name.formatted` (the name), and `active`.
Everything else a SCIM payload carries — `externalId`, `title`, `department`, `addresses`,
`phoneNumbers`, `locale` — is accepted and dropped. There is nowhere to put it, and rejecting
the request would stall the connector's whole sync over a field nobody asked us to keep.

---

## Groups → project roles

A project has three roles (`services/roles.py`), so a project exposes three groups, with ids
`{project id}:{role}`. Because `WorkspaceMember.role` is a **single column**, they are mutually
exclusive by construction:

* **`add`** sets the role. Adding someone to `7:member` is what removes them from `7:viewer`.
  Adding a deprovisioned account restores it properly (membership, plus a usable login) rather
  than leaving a membership row it can never sign in to use.
* **`remove`** removes their membership of the project. It is **not** a deactivation: the
  account keeps its password and its sessions, it just has no access to this project. Use
  `active: false` when the person has left. Removing someone already absent is a no-op, not a
  404, so a connector can safely re-send.
* **`replace`** on `members` is **refused** with a 400. Against one role column it cannot
  express the difference between "these are now the owners" and "everyone else loses the
  project", and either guess is wrong in a way that either leaves privilege behind or removes
  people the IdP never touched. Configure your connector to push group membership as
  add/remove.

---

## Provisioning a new person

`POST /Users` creates the account, adds them to the project as `member` (the same default as
`POST /api/projects/{id}/members`), and gives them an **unguessable random password nobody
knows** rather than an empty one — an empty hash would make `forgot` refuse to send a reset
link and leave them permanently locked out. Their first login is therefore the existing
**Forgot password** flow.

**SCIM does not send an invitation email.** Tell provisioned users to use "Forgot password", or
send your own welcome mail from the IdP. This is a genuine rough edge, not a design position.

An address that already has a ProveKit account **joins the project** instead of being rejected —
the same thing the members API does, and the only behaviour that works on an instance where
people signed up before SCIM was switched on. Already a member → 409 `uniqueness`.

---

## Audit trail

Every SCIM change to *access* writes an `AuditLog` row: `scim.user.provision`,
`scim.user.deprovision`, `scim.user.reactivate`, `scim.user.delete`, `scim.role.change`. The
deprovision row records whether login was disabled and how many memberships remained.

Attribute-only edits (`displayName`, `userName`) are **not** audited — they grant nothing, and
this table exists for privileged change, not for a change feed.

Two further caveats:

* **`actor_email` is blank.** The actor is an identity provider, not a ProveKit account, and
  there is no service-principal actor in the schema. `detail.via` is `"scim"`.
* **These do not appear in a project's activity feed yet.** The feed renders an allowlist
  (`audit.TENANT_VISIBLE`) with human phrasing in `audit.LABELS`, and this change did not own
  `services/audit.py`. The rows are written and readable in the platform audit view; adding
  them to the feed is a two-line change in that file.

---

## Offboarding checklist

SCIM covers the first item and nothing else on this list:

1. ☑ `PATCH /Users/{id}` `active: false` — sessions revoked, project access gone, login and
   self-service recovery disabled.
2. ☐ **Rotate the project's API keys** (Settings → API keys). SCIM cannot tell which ones they
   had.
3. ☐ Accept, or act on, outstanding share links — they are stateless and cannot be listed or
   revoked one at a time (see above).
4. ☐ If they were a platform operator, remove them from `SUPERUSER_EMAILS` and clear
   `is_superuser` in the admin console.
