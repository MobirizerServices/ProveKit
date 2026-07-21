# ProveKit docs

- [Features](../FEATURES.md) — the full inventory of what's built
- [Changelog](../CHANGELOG.md) — what shipped, release by release

**Guides**

- [Tracing guide](TRACING.md) — the decorator, `pk.span()`, configuration, what's captured
- [Debugging guide](DEBUGGING.md) — edit & re-run a captured call, replay a flow, model connections
- [Evaluation guide](EVALUATION.md) — datasets, scorers, `pk.evaluate()`, experiments, CI gates
- [MCP debug channel](MCP.md) — debug traces from Claude Desktop / Cursor by project key
- [Examples](../examples/README.md) — runnable demo agents (incl. LangGraph) that fill a portal

**Deploy & release**

- [Admin console](ADMIN.md) — platform operators: bootstrapping superusers, what `/admin` shows
- [Deployment](DEPLOY.md) — local vs hosted (TLS, Postgres, Redis)
- [Deploy to a dedicated VPS](DEPLOY_PROVEKIT_ONLINE.md) — **canonical**: how provekit.online runs
- [Shared VPS](DEPLOY_CONTABO_SHARED.md) · [host toggle](DEPLOY_CONTABO_TOGGLE.md) — co-hosting setups
- [Publishing](PUBLISHING.md) — release `provekit` to PyPI

**Design & planning**

- [Interactive debugging design](design/INTERACTIVE_DEBUGGING.md) — architecture behind edit-and-re-run
- [Roadmap (100)](ROADMAP_100.md) — **current**: the gap between ProveKit today and a product teams bet on
- [Roadmap (original)](ROADMAP.md) — the research-backed feature menu; largely delivered, kept for context
- [Landing roadmap](LANDING_ROADMAP.md) — 100 points to a production-ready marketing site
- [UI roadmap (200)](UI_ROADMAP_200.md) — path to a world-class, production-ready portal
- [Agent flow (50)](AGENTFLOW_50.md) — full-bleed canvas, inspector, node CTAs, collapse
- [Launch kit](launch/LAUNCH_KIT.md) — ready-to-post Show HN / tweet / PH copy + checklist

**Project**

- [Contributing](../CONTRIBUTING.md) — clone to running
- [Security](../SECURITY.md) — threat model, secret handling, disclosure

## The 60-second tour

1. Sign in to the portal and create a project → copy its key.
2. `pip install "provekit[trace]"`, put the key + endpoint in `.env`.
3. Add `@pk.trace(name="my-agent")` at your agent's entrypoint and run it.
4. Open **Traces** — your run appears as a nested flow: the entrypoint, the model calls,
   the tools, each with its input and output.
