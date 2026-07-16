# The `.agentman` file format

Plain-text, git-diffable agent tests and flows. A test file is the unit you commit,
review, and run in CI; it bundles one request, its assertions, and an optional
dataset of input rows. **Credentials never enter a file** — connections are
referenced by name and resolve against the local workspace at import/run time.

Suggested repo layout:

```
.agentman/
  tests/
    support-bot.yaml
    latency-slo.yaml
  flows/
    triage.yaml
```

## Test files (`kind: test`)

```yaml
version: 1
kind: test
name: Support bot regression
connection: OpenAI (prod)          # resolved by name — never an id, never a key
request:
  type: prompt                     # prompt | tool | agent
  model: gpt-4o-mini
  system: You are a support assistant.
  user: "{{message}}"              # {{vars}} come from the dataset rows / environment
  temperature: 0.2
  max_tokens: 512
assertions:
  - type: contains
    value: refund
  - type: latency_lt
    value: 3000
dataset:                            # optional — omit for a single-shot test
  - name: angry customer
    variables: {message: "URGENT: my order never arrived, refund now"}
  - name: plan question
    variables: {message: "How do I change my plan?"}
```

Request shapes by type:

| type | fields |
|---|---|
| `prompt` | `model`, `system`, `user`, `messages`, `temperature`, `max_tokens` |
| `tool` (MCP) | `tool`, `args` |
| `agent` (HTTP) | `method`, `path`, `headers`, `body`, `stream` |

Assertion types: `contains` · `equals` · `regex` · `json_path` · `json_schema` ·
`tool_called` · `latency_lt` · `llm_judge` (fields: `path`, `value`, `schema`,
`criteria`, `model` as applicable).

## Flow files (`kind: flow`)

```yaml
version: 1
kind: flow
name: Inventory check
description: Check stock via MCP, branch on availability.
nodes:
  - id: input
    type: input
    position: {x: 40, y: 140}
    data: {title: Input}
    config: {sample: {product: Berge}}
  - id: tool
    type: tool
    position: {x: 320, y: 140}
    data: {title: Check stock}
    config:
      connection: Magari · catalog (MCP)   # name, not id
      tool: check_inventory
      args: {product: "{{input.product}}"}
edges:
  - {id: e1, source: input, target: tool}
```

## Guarantees

- **Stable field order** — the same request always serializes to the same bytes,
  so diffs show real changes only.
- **No secrets** — `api_key` and workspace-local `connection_id` are stripped on
  export; files containing an `api_key` are rejected on import.
- **Portable** — importing into a workspace resolves `connection` names; an
  unresolved name still imports and just needs a connection re-picked.

## API

- `GET  /api/requests/{id}/export` → YAML test file
- `GET  /api/flows/{id}/export` → YAML flow file
- `POST /api/import {content}` → creates the request (+ dataset) or flow

The `agentman` CLI runs these files headless for CI.
