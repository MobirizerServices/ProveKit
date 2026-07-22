# MCP debug channel

Debug your agent traces from any MCP client — Claude Desktop, Cursor, or your own — by
letting an assistant query the runs ProveKit already captured, reason about what broke, and
turn a failure into a regression test.

**This is not a second client SDK.** Your traced app still installs only the one `provekit`
tracing SDK. The MCP server is a *debug channel*: it runs wherever you like and talks to your
portal over HTTP, authenticated by the same project key. Traces still flow one way — SDK →
portal — and MCP/REST are how you read them back and curate what you found.

```
  your agent (one SDK)                     portal                MCP client (Claude/Cursor)
  provekit ──OTLP──▶ /v1/traces ──▶ DB ──▶ /v1/traces (GET) ◀── provekit-mcp
                                      └──▶ /v1/datasets (POST) ◀─┘
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

## Read tools

| Tool | What it does |
|---|---|
| `provekit_list_traces(limit, status?)` | Recent traces, newest first. `status="failed"` filters to failures. |
| `provekit_list_failures(limit)` | Just the traces that ended in a failure — start here. |
| `provekit_get_trace(trace_id)` | The full span tree of one trace, to inspect what happened. |
| `provekit_list_datasets()` | This project's datasets with id, name and item count. |
| `provekit_preview_dataset_item(trace_id, span_id?, dataset_id?)` | The exact `{input, expected}` a promotion would write, and where it would land. Writes nothing. |

With these, you can ask an assistant things like *"what failed in the last hour?"* or
*"pull trace `abc123` and explain where the agent went wrong"* — and it reads the real spans
(model calls, tools, HTTP, logs) to answer, with no code added to the traced app.

## Write tools

| Tool | What it changes |
|---|---|
| `provekit_add_trace_to_dataset(dataset_id, trace_id, span_id?, expected?, allow_duplicate?)` | Appends **one** `{input, expected}` item, built from a trace's root span (or the span you name). |
| `provekit_create_dataset(name, description?)` | Creates one **empty** dataset. |
| `provekit_start_experiment(dataset_id, name)` | Registers one experiment over a dataset. Runs nothing. |

These close the loop the channel exists for:

> *"Find what failed this morning, add the worst one to the `regression` dataset with the
> answer it should have given, and register tonight's eval."*

The assistant previews the item, shows you the input and expected it's about to write and the
dataset it's writing to, then appends. The failing run's recorded output is the *wrong* answer,
so pass `expected=` for those — otherwise the recorded output is kept as `expected` (the same
rule as seeding an item from a trace in the portal).

### The rules writes play by

Handing an assistant a write tool is not the same as handing it a read tool, so:

- **Nothing is destructive.** There is no delete tool and no edit tool. Every write appends.
  The worst outcome is a row you remove in the portal — never a curated item you lose, and
  never a rewritten `expected` that silently changes what past experiments were scored
  against. Deleting a dataset, deleting an item and deleting an experiment stay portal-only
  for that reason; so does editing an item, because an in-place edit can't be undone from the
  experiment results that were scored under the old value.
- **Preview before write.** `provekit_preview_dataset_item` renders the exact item, the target
  dataset's name and size, and whether that span is already in it.
- **The target is named back.** Every write resolves `dataset_id` first and echoes the dataset
  *name* in its result, so "wrote to dataset 7" is checkable. Names are never resolved to ids —
  an id comes from `provekit_list_datasets` or it doesn't come at all.
- **Ambiguity is refused, not guessed.** Promoting the same span twice, creating a second
  dataset with a name in use, promoting a span that recorded no input, promoting from a trace
  with no root span, and evaluating an empty dataset all raise — with the id you probably
  meant — and write nothing.

`provekit_start_experiment` **does not run your eval.** ProveKit can't call your agent, so the
experiment it registers is an empty container until something that *can* run your target posts
results into it — `pk.evaluate(...)` from your code or CI, or `POST
/v1/experiments/{id}/results`. Use it when a run needs an id up front; otherwise just run
`pk.evaluate`, which registers its own.

## Under the hood

The server is a thin client over the key-authed API:

- `GET /v1/traces?limit=&status=` — list traces for the project the key belongs to
- `GET /v1/traces/{trace_id}` — every span of one trace
- `GET /v1/datasets`, `GET /v1/datasets/{id}/items` — datasets and their contents
- `POST /v1/datasets`, `POST /v1/datasets/{id}/items` — create a dataset, append an item
- `POST /v1/experiments` — register an experiment over a dataset

Promotion happens client-side: the server pulls the span tree, picks the span, and posts a
plain item — which is how span-level promotion works at all (the portal's own from-trace
seeding only ever takes the root). Items carry `meta = {trace_id, span_id, source: "mcp"}`,
so every promoted example points back at the run it came from.

These are the same rows the portal's **Traces** and **Datasets** views show (those views are
cookie-authed; these are key-authed) — so REST, the UI, and MCP are three doors onto one
dataset. The key-authed surface is strictly append-only: destructive operations exist only
behind a session.

## Other channels

The key-authed `/v1` endpoints are plain REST — script against them directly, or wire them
into a dashboard or a CI check, without the MCP layer. A nightly job can append yesterday's
failures to a dataset with the same two POSTs the MCP tools use. The rule holds either way:
**one SDK at the client; every debug and curation channel lives on the portal side.**
