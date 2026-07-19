# MCP debug channel

Debug your agent traces from any MCP client — Claude Desktop, Cursor, or your own — by
letting an assistant query the runs ProveKit already captured, and reason about what broke.

**This is not a second client SDK.** Your traced app still installs only the one `provekit`
tracing SDK. The MCP server is a *read-side debug channel*: it runs wherever you like and
pulls already-captured traces from your portal over HTTP, authenticated by the same project
key. Data flows one way — SDK → portal — and MCP/REST are how you read it back.

```
  your agent (one SDK)                     portal                MCP client (Claude/Cursor)
  provekit ──OTLP──▶ /v1/traces ──▶ DB ──▶ /v1/traces (GET) ◀── provekit-mcp
```

## Run it

```bash
pip install "provekit[mcp]"
export PROVEKIT_API_KEY=pk_...                       # your project key (same as ingest)
export PROVEKIT_ENDPOINT=https://provekit.your-co.com
provekit-mcp                                         # speaks MCP over stdio
```

Register the `provekit-mcp` command with your MCP client. For Claude Desktop, add it to the
`mcpServers` block of the config (adjust the path/env to your setup):

```json
{
  "mcpServers": {
    "provekit": {
      "command": "provekit-mcp",
      "env": {
        "PROVEKIT_API_KEY": "pk_...",
        "PROVEKIT_ENDPOINT": "https://provekit.your-co.com"
      }
    }
  }
}
```

## Tools it exposes

| Tool | What it does |
|---|---|
| `provekit_list_traces(limit, status?)` | Recent traces, newest first. `status="failed"` filters to failures. |
| `provekit_list_failures(limit)` | Just the traces that ended in a failure — start here. |
| `provekit_get_trace(trace_id)` | The full span tree of one trace, to inspect what happened. |

With these, you can ask an assistant things like *"what failed in the last hour?"* or
*"pull trace `abc123` and explain where the agent went wrong"* — and it reads the real spans
(model calls, tools, HTTP, logs) to answer, with no code added to the traced app.

## Under the hood

The server is a thin client over the key-authed read API:

- `GET /v1/traces?limit=&status=` — list traces for the project the key belongs to
- `GET /v1/traces/{trace_id}` — every span of one trace

These are the same rows the portal's **Traces** view shows (that view is cookie-authed;
these are key-authed) — so REST, the UI, and MCP are three doors onto one dataset.

## Other channels

The key-authed `GET /v1/traces` endpoints are plain REST — script against them directly, or
wire them into a dashboard or a CI check, without the MCP layer. The rule holds either way:
**one SDK at the client; every debug/read channel lives on the portal side.**
