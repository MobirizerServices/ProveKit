# ProveKit docs

- [Features](../FEATURES.md) — the full inventory of what's built
- [Tracing guide](TRACING.md) — the decorator, `pk.span()`, configuration, what's captured
- [Publishing](PUBLISHING.md) — release `provekit` to PyPI
- [Deployment](DEPLOY.md) — local vs hosted (TLS, Postgres, Redis)
- [Contributing](../CONTRIBUTING.md) — clone to running
- [Security](../SECURITY.md) — threat model, secret handling, disclosure

## The 60-second tour

1. Sign in to the portal and create a project → copy its key.
2. `pip install "provekit[trace]"`, put the key + endpoint in `.env`.
3. Add `@pk.trace(name="my-agent")` at your agent's entrypoint and run it.
4. Open **Traces** — your run appears as a nested flow: the entrypoint, the model calls,
   the tools, each with its input and output.
