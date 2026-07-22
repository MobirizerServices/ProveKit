# Terraform provider

There is a working Terraform provider skeleton in [`terraform/`](../terraform/) covering
`provekit_project`, `provekit_api_key` and `provekit_alert`. **It is a prototype and it is not
usable as a supported integration.** This document says exactly why, so nobody reads the
directory listing and concludes ProveKit has a Terraform story.

Two facts up front, both of which the [README](../terraform/README.md) repeats:

- **The code has never been compiled.** Go was not installed in the environment it was
  written in. No `go.sum`, no `go build`, no `go vet`, no test run.
- **It talks to `/api/*`, which carries no compatibility promise.**

The second one is the interesting one.

## The blocker: there is no `/v1` control plane

A provider is a contract against an API. [API_STABILITY.md](API_STABILITY.md) draws that
contract in three tiers, and the covered one — the tier with a 180-day deprecation window —
is `/v1`, authenticated with a `pk_` project key as a bearer token.

Here is every `/v1` route the server exposes today:

```
POST   /v1/traces                         GET  /v1/datasets
GET    /v1/traces                         POST /v1/datasets
GET    /v1/traces/{trace_id}              GET  /v1/datasets/{id}/items
GET    /v1/traces/{trace_id}/cassette     POST /v1/datasets/{id}/items
GET    /v1/traces/{trace_id}/feedback     POST /v1/experiments
POST   /v1/traces/{trace_id}/feedback     GET  /v1/experiments/{eid}
GET    /v1/share/{token}                  POST /v1/experiments/{eid}/results
GET    /v1/export/traces.ndjson           GET  /v1/experiments/judge-calibration
GET    /v1/export/estimate
```

Traces, datasets, experiments, share, export. **No projects. No keys. No alerts.** The three
things roadmap #97 asks for are exactly the three things `/v1` does not have.

They exist only as:

| Resource | Route | Router | Auth |
|---|---|---|---|
| Project | `/api/projects` | `routers/projects.py` | `get_current_user` — session cookie |
| Project key | `/api/api-keys` | `routers/apikeys.py` | `current_workspace` → session cookie + `X-Project-Id` |
| Alert | `/api/alerts` | `routers/alerts.py` | `current_workspace` → session cookie + `X-Project-Id` |

Every one of those is Internal tier. API_STABILITY.md's wording is not hedged:

> **`/api/*`.** These are cookie-authed and exist to serve the bundled frontend […] They
> change whenever the UI changes, in the same commit, with no notice. If you find yourself
> scripting against `/api`, that's a request for a `/v1` equivalent — open an issue rather
> than pinning a version.

That paragraph is a description of this provider. Publishing it would ship a promise the
project has explicitly declined to make: a UI refactor lands, `_AlertPatch` gains a field or
`_public()` renames one, and someone's `terraform apply` breaks in a release that was
correctly labelled non-breaking.

There is a second, sharper consequence. `services/auth.get_current_user` reads the
`agm_session` cookie and has no bearer branch, so the provider must **log in with an email and
password** and carry a session cookie. That means infrastructure-as-code holding a human's
account password — the exact credential shape Terraform users spend effort avoiding. A `pk_`
key would 401 on all three routes.

## So why is the code here at all?

Because the roadmap already answers the "should we build this" question, and the answer is
not yet:

> **What I'd deliberately defer:** SCIM (#78), **Terraform (#97)**, residency (#86), custom
> renderers (#99), and time-travel (#56). Each is real, and each is a *response to demand you
> don't have yet* — build them when a named user asks.

Given that, the useful deliverable is not a shipped provider. It is the smallest artifact that
makes the next decision cheap:

1. **It prices the work.** Three resources, full CRUD, import, drift detection and plan-time
   validation is about 800 lines of Go. The provider is not the hard part.
2. **It names the hard part precisely.** The `/v1` control plane is the dependency, and the
   provider is what makes that concrete rather than abstract. See "What the API shape forces
   on you" in the README: no `GET /{id}` on any of the three, so every read lists and filters;
   keys have no update route at all; alerts can only toggle `enabled`. Those are not provider
   quirks, they are what a UI-shaped API looks like when something non-UI drives it. A `/v1`
   design should fix them at the source rather than make every client work around them.
3. **When a named user does ask, this is a week's head start, not a blank page.**

## What would have to happen first

In order:

1. **`/v1` projects, keys and alerts** — bearer-authed with a `pk_` key, per-object `GET`
   routes, a real update route for alerts, and coverage by the deprecation window. Note that
   a project key is scoped to one project, so minting keys and creating projects need a
   thought-through auth story rather than a copy of the cookie routes; that design is the
   actual work in #97, not the Go.
2. Everything in the README's **"What a published provider would additionally need"** list —
   compile and vet in CI, acceptance tests against a live instance, `tfplugindocs`, GoReleaser
   with a registered GPG signing key, and a `terraform-provider-provekit` repo under a claimed
   registry namespace.

Until step 1 exists, the honest status of Terraform support in ProveKit is: **none, with a
prototype on the shelf and a clear reason it is still there.**

## Trying it anyway

Build and `dev_overrides` instructions are in [`terraform/README.md`](../terraform/README.md).
Point it at a local instance, not a production one — `terraform destroy` on a
`provekit_project` deletes every run, dataset, experiment, feedback row, alert and key in that
project, because that is what `DELETE /api/projects/{id}` does.
