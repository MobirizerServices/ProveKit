# ProveKit docs

- [Quickstart & contributing](../CONTRIBUTING.md) — clone to running in ~2 minutes
- [`.provekit` file format](FILE_FORMAT.md) — git-diffable tests & flows
- [LangGraph starter](../examples/langgraph-starter/) — test a framework agent from the
  outside (serve wrapper + `.provekit/` tests + CI workflow), no SDK
- [Deployment](DEPLOY.md) — local vs hosted (TLS, Postgres, Redis)
- [Product strategy](PRODUCT_STRATEGY.md) — positioning, competitive analysis, roadmap
- [Security](../SECURITY.md) — threat model, secret handling, disclosure
- [Changelog](../CHANGELOG.md)

## The 60-second tour

1. `make setup && make backend && make frontend`, open http://localhost:3001
2. Run the seeded **Demo Assistant (mock)** — streams an answer, no key needed.
3. Click **+ contains** on the result to turn it into an assertion; run again to check it.
4. Open a **Flow**, hit **Run** to watch nodes execute, then **▲ Deploy** to publish it as
   an API endpoint (you get a URL + one-time key + a ready `curl`).
5. `provekit run .provekit/tests/` runs your saved tests headless in CI.
