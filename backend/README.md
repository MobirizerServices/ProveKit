# ProveKit

**Prove your agent works.** ProveKit tests any AI agent — an LLM API, an MCP server, an
HTTP agent, or an A2A agent — turns a run into a regression test, and runs the suite
headless in CI. Open-source, local-first, no account.

This package is the **`provekit` CLI** — the headless test runner. The full visual app
(console, flow builder, live step-debugger) runs as a server; see the
[repo](https://github.com/MobirizerServices/ProveKit).

## Install

```bash
pip install provekit
```

## Use in CI

Write plain-text, git-diffable tests under `.provekit/` (connections referenced by name,
secrets via `${ENV_VAR}` — never in the files), commit them, and run:

```bash
provekit run .provekit/tests/                      # pretty output, non-zero exit on failure
provekit run .provekit/tests/ --format junit -o results.xml
provekit import-promptfoo promptfooconfig.yaml -o .provekit/tests/   # migrate from promptfoo
```

Connections resolve from `.provekit/connections.yaml`:

```yaml
connections:
  OpenAI (prod):
    provider: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o-mini]
```

## Assertions

`contains` · `equals` · `regex` · `json_path` · `json_schema` · `tool_called` ·
`latency_lt` · `llm_judge` — pass/fail per assertion, non-zero exit on failure.

## Links

- Repository & full app: https://github.com/MobirizerServices/ProveKit
- File format: see `docs/FILE_FORMAT.md` in the repo
- License: MIT
