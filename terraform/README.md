# terraform-provider-provekit

A Terraform provider for ProveKit projects, project keys and alerts, built on
[terraform-plugin-framework](https://github.com/hashicorp/terraform-plugin-framework).

**Status: prototype, not a shipped integration.** Two things are true about this directory
and you should read both before using it.

1. **It has never been compiled.** Go is not installed in the environment this was written
   in. There is no `go.sum`, `go build` has not run, `go vet` has not run, and the tests in
   `internal/provider/client_test.go` have not been executed. The code is written to be
   correct and complete rather than sketched — every request path, body and status code below
   was read out of the FastAPI routers it talks to — but "written carefully" is not "known to
   compile". Assume the first `go build` finds something.
2. **It drives the internal API.** ProveKit's stable surface is `/v1`, and `/v1` has no
   projects, no keys and no alerts — it is traces, datasets, experiments, share and export.
   Everything this provider manages lives under `/api/*`, which
   [docs/API_STABILITY.md](../docs/API_STABILITY.md) classifies as *Internal — "No promise at
   all; changes without notice."* See [docs/TERRAFORM.md](../docs/TERRAFORM.md) for what that
   means and what would have to happen first.

## Resources

| Resource | Endpoints | Notes |
|---|---|---|
| `provekit_project` | `POST/GET/PATCH/DELETE /api/projects` | Destroy deletes every run, dataset, experiment, alert and key in the project. |
| `provekit_api_key` | `POST/GET/DELETE /api/api-keys` | Every attribute forces replacement — there is no update route. Destroy revokes (soft). |
| `provekit_alert` | `POST/GET/PATCH/DELETE /api/alerts` | Only `enabled` updates in place; the PATCH body has exactly one field. |

No data sources yet. A `provekit_project` data source is the obvious next thing and would read
the same internal listing route, so it waits on the same work.

### Things the API shape forces on you

These are consequences of the endpoints, not choices, and they will surprise someone:

- **There is no `GET /api/{thing}/{id}` for any of the three.** Every read lists the
  collection and filters client-side. It is correct and it is O(n) per resource per refresh.
- **`provekit_api_key.key` is write-once.** The plaintext is returned by `POST` and never
  again; only its SHA-256 hash is stored. So it lives in Terraform state and nowhere else,
  and a key brought in with `terraform import` has `key = null` permanently.
- **Revoking is not deleting.** `terraform destroy` on a key sets `revoked = true` and leaves
  the row so last-used history survives. The provider treats a revoked key as absent on read,
  so revoking one in the portal makes Terraform plan a replacement.
- **Alerts do not run themselves.** They are evaluated by `POST /api/alerts/check`. Creating
  one here does not schedule anything; you still need a cron hitting that endpoint.
- **The server silently truncates** `name` to 160 characters, `email` to 255, `webhook_url` to
  500. For `provekit_project.name` and `provekit_alert.metric`, which are `Required` and not
  computed, exceeding the limit will surface as Terraform's "provider produced inconsistent
  result after apply" rather than a clean validation error. Keep names short.
- **Auth is a session cookie, not a project key.** These routes go through
  `services/auth.get_current_user`, which reads the `agm_session` cookie and has no bearer
  branch. A `pk_` key 401s on all of them. That is why the provider takes an email and
  password.

## Build

```bash
cd terraform
go mod tidy     # writes the indirect requires and go.sum — required, none is committed
go build ./...
go test ./...
```

## Local install via dev_overrides

`dev_overrides` points Terraform at a binary on disk instead of the registry. Nothing is
published, so this is the only way to run it.

Build and install it somewhere on your path:

```bash
cd terraform
go build -o ~/go/bin/terraform-provider-provekit
```

Then in `~/.terraformrc` (`%APPDATA%\terraform.rc` on Windows):

```hcl
provider_installation {
  dev_overrides {
    "provekit/provekit" = "/Users/you/go/bin"
  }
  # Everything not overridden still resolves normally.
  direct {}
}
```

The value is the **directory** containing the binary, not the binary itself, and the key must
match the `Address` in `main.go` (`registry.terraform.io/provekit/provekit`, which shortens to
`provekit/provekit`). Get either wrong and Terraform does not error — it quietly falls back to
the registry and fails to find a provider that was never published.

With an override active, **do not run `terraform init`**; it will fail on a provider it cannot
download. Go straight to `plan`/`apply`. Terraform prints a warning on every command reminding
you the override is in effect, and it will refuse to create a lock file. That is expected.

```bash
cd examples/basic
export PROVEKIT_EMAIL=you@example.com
export PROVEKIT_PASSWORD=...       # omit both on an instance running with HOSTED=false
terraform plan
```

## Provider configuration

| Argument | Environment variable | Default |
|---|---|---|
| `endpoint` | `PROVEKIT_ENDPOINT` | `http://localhost:8000` |
| `email` | `PROVEKIT_EMAIL` | — |
| `password` | `PROVEKIT_PASSWORD` | — |

Set both credentials or neither. Neither is valid only against an instance running with
`HOSTED=false`, where the server hands every request a local user and no login exists to do.
Prefer the environment variables: a password in a `.tf` file is a password in git.

The provider logs in once during `Configure` and then calls `GET /api/auth/me`, so a wrong
endpoint or a bad password is one clear error at plan time rather than one per resource.

## Importing

`provekit_project` imports by id. The other two need the project too, because reading them
requires knowing which tenant to ask:

```bash
terraform import provekit_project.checkout_agent 3
terraform import provekit_api_key.ci 3:17          # project_id:key_id
terraform import provekit_alert.error_rate 3:9     # project_id:alert_id
```

## What a published provider would additionally need

Nothing below is done. This list is the gap between this directory and something you could put
in a registry, in rough dependency order:

1. **A `/v1` control plane.** The blocker. Publishing a provider against `/api/*` publishes a
   promise ProveKit has explicitly declined to make, and the first UI refactor breaks every
   user's `terraform apply`. `/v1` equivalents of projects, keys and alerts — bearer-authed,
   covered by the deprecation window — come first; everything else is mechanical.
2. **A compile, and a vet, and a lint.** `go build`, `go vet`, `golangci-lint`, in CI.
3. **Acceptance tests against a live instance.** `terraform-plugin-testing` with `TF_ACC=1`,
   running real create/read/update/destroy cycles plus import and drift steps against a
   disposable ProveKit. Unit tests on helpers prove nothing about a provider; the CRUD
   round-trip is the only thing that does, and none of it has run.
4. **Generated docs.** `tfplugindocs` renders `docs/` from the schemas; the registry requires
   that layout, and hand-written resource docs go stale immediately.
5. **Release engineering.** GoReleaser cross-compiling per OS/arch, a GPG signing key whose
   public half is registered with HashiCorp, signed `SHA256SUMS`, and a GitHub release per
   tag. The registry rejects unsigned releases.
6. **Registry publishing.** A `terraform-provider-provekit` repo (the registry requires that
   exact name and its own repository), the namespace claimed, the signing key uploaded, and a
   version scheme decided — the provider's version is not ProveKit's.
7. **A support answer.** Which ProveKit versions a given provider version works against, and
   what happens to someone's state when it doesn't.
