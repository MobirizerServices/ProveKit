# Bulk export

Stream a project's spans out as NDJSON, so trace data can join the rest of a company's
analytics — cost per customer, latency against deploys, quality against a support queue. One
JSON object per line, UTF-8, newline-delimited: Snowflake, BigQuery, Redshift, DuckDB, Spark and
`jq` all read it without help.

Two things on this page are more important than the endpoint reference, and are near the top for
that reason: **what an export contains** (it is not masked) and **what resolving offloaded
payloads costs**.

---

## Status

| Part | State |
|---|---|
| On-demand streaming export (`services/export.py`, `routers/export.py`) | written and unit-tested |
| Routes reachable over HTTP | **pending wiring** — see below |
| Scheduled export to an HTTP destination | **shipped.** [Endpoints](#scheduled-export) |
| Scheduled export to S3 / GCS | **not shipped.** [What's left](#scheduled-export--whats-still-missing) |

### Wiring

`provekit/routers/export.py` is not registered yet. Until these two lines are added to
`provekit/main.py` (next to the other `include_router` calls), every path below is a 404:

```python
app.include_router(export.router)
app.include_router(export.key_router)
```

…with `export` added to the `from .routers import (...)` list at the top of that file. The HTTP
tests in `backend/tests/test_export.py` skip themselves until the routes are present and start
running the moment they are.

---

## What an export contains

**Everything stored, verbatim. Export is not a share link.**

A share link (`/v1/share/{token}`) runs every span through `share.mask_span_rows` on the way out,
so the withheld text is not in the response body at all. **The export path does not go anywhere
near that code.** `request.input` and `result.text` in an export are the actual prompts and
actual completions, including whatever your agents put in them — customer names, ticket bodies,
addresses, whatever the model was handed.

The only masking that can ever have touched these rows happened at *ingest*, before they were
stored: `services/redact.py`, enabled per project (`redact_pii`) or globally (`REDACT_PII`). It
is **off by default** and it is pattern-based — emails, card numbers, SSNs, provider keys, phone
numbers. It is a net, not a guarantee, and it cannot retroactively clean rows that were stored
before you turned it on. If you need an export that is safe to hand to a third party, the
redaction has to have been on at ingest time; there is no masking pass on the way out.

What an export does **not** contain: users, password hashes, API key hashes, sealed provider
credentials, other projects' spans. It is `runs` rows for exactly one project, and every row
carries its own `workspace_id` so you can assert in the warehouse that you exported the tenant
you meant to.

**Who can do it.** Any member of the project, including a `viewer`. That is deliberate rather
than an oversight: a viewer can already read every trace one at a time through `/api/traces`, so
export changes the ergonomics of a bulk read, not the authorization for it. If bulk extraction is
a separate risk in your deployment, the controls that actually apply are not handing out project
keys and putting `/v1/export` behind your proxy.

**Every export is audited.** One `audit_logs` row per request (`action = "export.traces"`) with
the actor's email, IP, the window asked for, and whether payloads were resolved. It is written
*before* the first byte, so it records the intent to export rather than the delivered byte count —
the generator outlives the request scope, and a client that disconnects halfway still got
whatever it got. Read it back from the platform audit trail
(`GET /api/admin/audit?action=export.traces`, superadmin) alongside grants and deletions.

---

## Offloaded payloads, and what resolving them costs

If `PAYLOAD_OFFLOAD_DIR` is set, `services/payloads.py` moves prompts over
`PAYLOAD_OFFLOAD_MIN_BYTES` to a blob store and leaves a reference in the row:

```json
{"__ref__": "sha256:9f86d081…", "bytes": 41233, "preview": "first 200 chars…"}
```

Exporting that as-is would write a *pointer* into your warehouse — to bytes your warehouse
cannot read, in a store it has no credentials for. The file would look complete and would not
be. So the export resolves references by default (`payloads.resolve_row`), and the price is
explicit:

- **One blob read per offloaded field, inline in the stream.** A 100k-span export where half the
  spans have an offloaded prompt is 50k object reads. On a local filesystem that is fractions of
  a millisecond each and disappears into the noise. On S3 at ~20 ms per GET, done serially, it is
  roughly *17 minutes* of latency that has nothing to do with the database — the blob store, not
  Postgres, becomes the thing you are waiting for.
- **The output is much larger than the table.** Offload exists precisely because those payloads
  are the bulk of the data; resolving them puts all of it back. Size the destination against your
  blob store, not against the `runs` table.
- **No prefetching.** The reads are serial because a concurrent prefetcher needs a bounded queue,
  its own error handling and a story for partial failure — a lot of machinery for an on-demand
  endpoint. Bound the work with `since`/`until` instead, and export more often.
- **A lost blob is visible, not silent.** If the store cannot return an object, the exported
  field is the 200-character preview followed by
  `[payload unavailable: sha256:… could not be read]`. Grep your export for
  `payload unavailable` after a large run: any hit means the blob store lost data, and it is not
  something the export can fix.

`resolve=false` skips all of it and exports the raw references. That is only useful when the
consumer can read the blob store itself — the sentinel line records `"resolved_payloads": false`
so a loader can tell the two kinds of file apart.

---

## Endpoints

Session-authed (the portal) and key-authed (cron, Airflow, a loader) doors onto the same stream:

| | |
|---|---|
| `GET /api/export/traces.ndjson` | session cookie, `X-Project-Id` selects the project |
| `GET /v1/export/traces.ndjson` | `Authorization: Bearer <project key>` |
| `GET /api/export/estimate`, `GET /v1/export/estimate` | row count for a window, before you commit to it |

| Parameter | Default | Meaning |
|---|---|---|
| `since` | — | ISO-8601 lower bound, inclusive. No offset means UTC. Garbage is a 422, never a silent "no filter" |
| `until` | — | ISO-8601 upper bound, **exclusive** — adjacent windows cannot double-count the row on their shared edge |
| `after_id` | `0` | incremental cursor: only rows with a higher `id` |
| `resolve` | `true` | resolve offloaded payloads (see above) |
| `limit` | `0` (all) | cap the rows — sample the shape before pointing this at a bucket |
| `sentinel` | `true` | append the completion line |

Response: `application/x-ndjson`, `Content-Disposition: attachment`, sent as it is read. Memory
on the server is O(chunk), not O(project) — `services/export.py` pages by primary key in blocks
of 500 and yields each row as it goes, so a project with millions of spans streams rather than
being built into a list first.

`estimate` returns `{"rows": N, "oldest": "…", "newest": "…"}` — a count and the window's real
edges, and deliberately nothing more. Anything richer (byte size, how many payloads are
offloaded) means reading the rows, which is the export itself.

---

## The record shape

```json
{
  "id": 84213,
  "workspace_id": 4,
  "trace_id": "1f0c…", "span_id": "a91b…", "parent_span_id": "", "session_id": "",
  "type": "llm", "label": "chat", "status": "completed",
  "duration_ms": 412, "error": "",
  "created_at": "2026-07-22T09:14:05.221+00:00",
  "model": "gpt-4o", "provider": "openai",
  "input_tokens": 1120, "output_tokens": 388, "cost_usd": 0.006680,
  "request": {"input": "…"}, "result": {"text": "…", "meta": {}}
}
```

- `id` is the export's stable identity — **use it as the warehouse's dedupe key**.
- `type` is `agent | llm | tool | step`; the tree is rebuilt from `span_id` / `parent_span_id`,
  and a root span has an empty `parent_span_id`.
- `created_at` is ingest time with an explicit `+00:00`, not a naive local-looking string.
- `model`, `provider`, `input_tokens`, `output_tokens`, `cost_usd` are lifted out of the JSON
  because they are what a warehouse actually groups by. They are lifted, not duplicated: the
  large text lives only in `request` / `result`, or every export would be twice the size it
  needs to be. `cost_usd` is priced at the rates that applied when the span was captured
  (`result.meta.price_version`), so a warehouse total matches the dashboard instead of being
  silently re-priced by a later rate change.

### The last line is not a span

```json
{"_export": {"status": "complete", "rows": 84213, "last_id": 84213,
             "resolved_payloads": true, "since": null, "until": null}}
```

A truncated NDJSON stream — dropped connection, database failure at row 300k — looks exactly
like a complete one, and a loader would quietly ingest a partial day. So the stream ends with a
sentinel carrying `status` (`complete` | `limit_reached` | `error`), the row count and the last
id. `status: "error"` also carries the message; the response was already `200` with a partial
body by then, so there is no status code left to change and saying it in the stream is the only
way you find out.

Drop it on the way in, and assert on it:

```bash
jq -c 'select(has("_export") | not)' export.ndjson > spans.ndjson
jq -c 'select(has("_export"))' export.ndjson        # must be exactly one line, status complete
```

A file with no sentinel line is a truncated file. `sentinel=false` if you would rather have a
strictly homogeneous file and accept losing that check.

---

## Incremental loads

Two cursors, and neither is exactly-once:

- **`after_id`** — store the sentinel's `last_id`, pass it back next time. This is the better one.
- **`since` / `until`** — a time window over ingest time (`created_at` is stamped when the row is
  written, not when the span ran, so a span exported late still lands in the window you fetch it
  in).

Why not exactly-once: ids are allocated at INSERT and `created_at` is stamped in Python, both
*before* commit. Under concurrent ingest a row with a lower id or an earlier timestamp can become
visible after you have already read past that point. So the correct pattern is the boring one —
**overlap and dedupe**: re-export the last few minutes each run and let the warehouse deduplicate
on `id`, which is stable forever.

**Retention interacts with this.** `_prune_runs` deletes a project's oldest spans past
`RUNS_RETENTION` on nearly every ingest. A span that is pruned before you export it is gone —
export more often than your retention window, and treat the warehouse as the archive rather than
the database. `GET /api/workspace/retention` tells you the policy and the oldest row still held.

---

## Scheduling it today

The key-authed door exists so this works from any scheduler you already run:

```bash
# hourly, with an overlap so a boundary row can't be lost
SINCE=$(date -u -d '75 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
OUT=/tmp/provekit-$(date -u +%Y%m%dT%H%M%SZ).ndjson

curl -fsS -H "Authorization: Bearer $PROVEKIT_KEY" \
  "https://provekit.example.com/v1/export/traces.ndjson?since=$SINCE" -o "$OUT"

# a file with no sentinel is truncated — do not upload it
jq -e 'select(has("_export")) | ._export.status == "complete"' "$OUT" >/dev/null

gzip "$OUT" && aws s3 cp "$OUT.gz" \
  "s3://analytics/provekit/dt=$(date -u +%F)/" --content-encoding gzip
```

Use `/v1/export/estimate` first if you do not know how big a window is. `curl -f` plus the
sentinel check is what keeps a failed or partial fetch from being uploaded as if it were a day's
data.

---

## Scheduled export

Shipped for HTTP destinations. A schedule is a row (`export_schedules`), so the cursor survives a
restart — which is the whole reason this needed a table rather than a config entry.

```bash
# create one (session-authed, from the portal or curl with a cookie)
curl -X POST $PROVEKIT_ENDPOINT/api/export/schedules \
  -H 'Content-Type: application/json' \
  -d '{"name":"warehouse","cadence":"daily","destination_url":"https://warehouse.example/ingest"}'

curl $PROVEKIT_ENDPOINT/api/export/schedules          # list, with last run + last error
curl -X POST $PROVEKIT_ENDPOINT/api/export/schedules/1/run   # run now, to prove a destination
curl -X DELETE $PROVEKIT_ENDPOINT/api/export/schedules/1
```

Each run POSTs NDJSON (`Content-Type: application/x-ndjson`) for everything above the stored
cursor, up to `MAX_ROWS` per delivery so a schedule that fell behind catches up over several runs
instead of building one request the destination can't accept. Cadence is `hourly | daily |
weekly`; a schedule that has never run is due immediately.

Four properties are worth knowing, because each is a way this feature fails quietly if built the
obvious way:

* **The cursor advances only after the destination accepts the batch.** A failed POST re-sends
  the same window next time rather than leaving a permanent hole nobody is told about.
* **Failures are recorded on the row** (`last_status`, `last_error`) and shown by the list
  endpoint. A scheduled export that stops silently is worse than none, because the warehouse
  keeps answering questions with stale data.
* **A schedule is claimed before it runs** — a conditional `UPDATE … WHERE claimed_until < now()`
  with a 10-minute lease. Replaying an ingest batch is idempotent so the spool drainer is safe
  under N workers; a scheduled export is not, and two workers firing the same schedule would
  double-count the window downstream. The lock is in the database on purpose: Redis is optional
  in this deployment and this must not be the feature that makes it mandatory.
* **The destination goes through `services/netguard.py`**, the same SSRF guard as alert webhooks
  and replay callbacks, so a schedule can't be aimed at cloud metadata or an internal service.

## Scheduled export — what's still missing

Named rather than implied:

* **S3 / GCS destinations.** Only HTTP POST is implemented. S3 needs multipart via boto3 (or a
  presigned PUT to avoid the SDK dependency) plus a sealed credential on the row —
  `services/sealing.py` is the mechanism, exactly as provider keys use it.
* **Object layout and compression.** `s3://bucket/prefix/project=<id>/dt=YYYY-MM-DD/part-<cursor>.ndjson.gz`
  — Hive-style partitioning so Athena and BigQuery external tables can prune, and gzip because
  NDJSON of resolved payloads compresses extremely well. Not meaningful until there is an object
  destination to lay out.
* **Notification on repeated failure.** `last_error` is visible if you look; `services/notify.py`
  would tell you without looking.
* **Cron expressions.** Three fixed cadences today, not arbitrary schedules.

## Scheduling it yourself

The key-authed door still exists and is unchanged, so driving exports from a scheduler you
already run works exactly as before — see [Incremental loads](#incremental-loads) above.
