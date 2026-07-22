# Ingest performance — measured, with conditions

Everything below is from runs of [`testkit/loadtest.py`](../testkit/loadtest.py) against a real
ProveKit process over HTTP on **22 July 2026**. No number here is modelled, scaled, or carried
over from another machine.

**Read the conditions before you use a number.** The single-box figures below were taken on a
laptop. They tell you the *shape* of the ingest path — where it saturates, what the spool costs,
which configuration knobs actually bind — and they are a floor for capacity planning. They do
**not** tell you what a server will do, and this page deliberately does not guess.

---

## TL;DR

| Question | Measured answer | Conditions |
|---|---|---|
| Spans/sec, default DB | **~10,300 spans/sec** (103 batches/sec of 100 spans) | SQLite/WAL, 1 uvicorn worker, M5 laptop, ingest rate limit lifted |
| Ingest latency at that rate | **p50 36 ms · p95 49 ms · p99 54 ms** per 100-span batch | same, 4 concurrent exporters |
| Spans/sec at **stock config** | **~1,130 spans/sec** — the rest is 429s | `INGEST_RATE_PER_MIN=600` caps one project at 10 batches/sec |
| Does it hold up? | **5.95M spans in 10 minutes at 9,920 spans/sec, 0 errors, 0 shed, flat RSS** | same box, one continuous run |
| Postgres? | **measured, but too noisy to publish as a capability** — see [Postgres](#postgres-measured-not-publishable) | Postgres in a Docker Desktop VM on the same laptop |
| What does the durability spool cost? | **~2.5% throughput, ~1 ms p50** | `SPOOL_ENABLED=true` vs `false` |

If you take one thing away: **a single ProveKit worker is one CPU core**, and on this box that
core did ~10k spans/sec of realistic OTLP. Size on cores and on your own measurement, not on this
page.

---

## The test bed

| | |
|---|---|
| Hardware | Apple M5, 10 cores, 16 GB RAM — a **laptop on AC power with other applications running**, not an isolated benchmark host |
| OS | macOS 27.0 (build 26A5378n), arm64 |
| Python | 3.12.13 |
| Server | `uvicorn provekit.main:app`, 1 worker unless stated, no `--reload` |
| Database | SQLite 3.53.1, WAL, on the internal SSD — **or** PostgreSQL 16.14 where stated |
| Load generator | `testkit/loadtest.py` on the **same machine** (loopback, no network) |
| Payload | 100 spans/batch, 10 spans/trace, ~400 B of prompt/completion text per span → **~99 kB request body** |
| Span shape | `gen_ai.*` v1.37 dialect: agent root + alternating `chat` / `execute_tool` children with token counts |

Loopback means **no network cost is included**. A real exporter over the internet adds its own
RTT to the latencies below; the throughput ceiling is unaffected.

### Configuration for the capacity runs

| Setting | Value used | Default | Why |
|---|---|---|---|
| `INGEST_RATE_PER_MIN` | `0` (off) | `600` | At the default you measure the rate limiter, not ingest — see [stock config](#what-the-stock-config-actually-allows) |
| `SPOOL_ENABLED` | `true` | `true` | Every batch is fsynced to disk before the ack (`services/spool.py`) |
| `SPOOL_DIR` | temp dir on the same SSD as the DB | temp dir | |
| `SPOOL_MAX_DEPTH` | `5000` | `5000` | Backpressure threshold — 503 + `Retry-After` above it; never reached in these runs |
| `SPOOL_DRAIN_SECONDS` | `5.0` | `5.0` | How often the background drainer replays staged batches |
| `MAX_BODY_BYTES` | `2000000` | `2000000` | Request-body cap; the 494 kB batches below are well under it |
| `RUNS_RETENTION` | `10000` | `10000` | Pruning runs on the ingest path — it is part of the cost |
| `REDIS_URL` | unset | unset | Rate-limit counters in-process |
| `REDACT_PII` | off | off | Redaction adds regex work per span; not measured here |

Every measured run is preceded by a 20 s prefill so the project is already **at** its retention
cap — i.e. every measured batch pays for pruning, which is the steady state of a long-running
instance. The harness also discards a 5 s warm-up before it starts counting.

---

## SQLite, one worker — the default self-hosted shape

Three consecutive 20 s runs, 4 concurrent exporters, 100 spans/batch:

| Run | spans/sec | p50 | p95 | p99 | max | errors | shed |
|---|---|---|---|---|---|---|---|
| 1 | 10,325 | 36.3 ms | 49.1 ms | 53.4 ms | 91.6 ms | 0 | 0 |
| 2 | 10,289 | 36.7 ms | 48.6 ms | 54.0 ms | 70.0 ms | 0 | 0 |
| 3 | 10,242 | 36.8 ms | 48.3 ms | 53.7 ms | 122.3 ms | 0 | 0 |

Spread across repeats is under 1%. `/healthz` reported `queue_depth: 0`, `lag_seconds: 0.0`,
`shed: 0` before and after every run — nothing was ever left staged.

### It saturates one core, not the box

Same config, one 20 s sample per row:

| Concurrent exporters | spans/sec | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 8,878 | 9.1 ms | 16.9 ms | 21.8 ms |
| 2 | 10,044 | 17.2 ms | 25.5 ms | 31.7 ms |
| 4 | 10,115 | 37.4 ms | 50.3 ms | 54.4 ms |
| 8 | 10,054 | 72.3 ms | 91.8 ms | 104.1 ms |
| 16 | 10,164 | 145.4 ms | 177.4 ms | 218.8 ms |

Throughput is flat from 2 exporters onward while latency grows in exact proportion to
concurrency. That is a single-threaded server: `POST /v1/traces` is an `async def` that does its
JSON decode, spool fsync and database write inline on the event loop, so batches queue behind one
another. **More exporters do not buy more throughput — they only buy latency.**

Three checks that this ceiling is the server's and not the harness's:

- `ps` during a 4-exporter run: the uvicorn process at **92.8% CPU** (one core of ten), each
  client process at ~6.5%.
- Splitting the load across **two client processes** (2 exporters each) gave 4,920 + 4,920 =
  **9,840 spans/sec aggregate** — the same ceiling as one process with 4 exporters, not double it.
- Generating a 100-span batch costs the harness **1.06 ms**, against a 36 ms server response.

### Batch size is the lever that matters

4 exporters, one 20 s sample per row:

| Spans/batch | Body size | batches/sec | spans/sec | p50 | p99 |
|---|---|---|---|---|---|
| 10 | 10 kB | 387.6 | 3,876 | 9.2 ms | 16.6 ms |
| 100 | 99 kB | 101.2 | 10,115 | 37.4 ms | 54.4 ms |
| 500 | 494 kB | 23.0 | 11,480 | 159.6 ms | 179.2 ms |

Per-request overhead dominates at small batches: **10x the batch size gave 2.6x the spans/sec**.
Above ~100 spans the gain flattens and only latency grows. ProveKit's SDK uses OTel's stock
`BatchSpanProcessor` without overriding its defaults (512 spans per export, 5 s schedule), so it
already sits in the good region; if something in your pipeline is sending 10-span batches, that is
where your throughput went.

Bodies are capped by `MAX_BODY_BYTES` (default 2 MB) — at ~1 kB/span that is roughly 2,000 spans
per request, and the harness warns before it exceeds it.

### 10-minute soak

One continuous 600 s run (after a 10 s warm-up), 4 exporters, 100 spans/batch, same SQLite
single-worker config:

```
spans/sec     9920.4   (99.2 batches/sec, 5,952,700 spans accepted, 5,895 MB sent)
latency ms    p50 37.57  p95 50.47  p99 61.03  max 246.74   (n=59,527)
requests      59527 total / 59527 ok / 0 429 / 0 503 / 0 other / 0 transport errors
```

**5.95 million spans, zero rejected, zero shed, zero transport errors.** Per-minute windows:

| Window | spans/sec | p50 | p95 | p99 |
|---|---|---|---|---|
| t+0s | 10,432 | 36.0 ms | 47.0 ms | 54.2 ms |
| t+60s | 10,193 | 36.6 ms | 49.7 ms | 61.8 ms |
| t+120s | 10,252 | 36.6 ms | 48.6 ms | 55.3 ms |
| t+180s | 9,650 | 38.8 ms | 51.8 ms | 57.9 ms |
| t+240s | 9,900 | 38.0 ms | 50.0 ms | 55.4 ms |
| t+300s | 9,818 | 38.7 ms | 48.4 ms | 55.6 ms |
| t+360s | 10,090 | 37.7 ms | 46.0 ms | 54.4 ms |
| t+420s | 10,005 | 38.0 ms | 49.5 ms | 54.6 ms |
| t+480s | 10,007 | 38.0 ms | 47.4 ms | 54.0 ms |
| t+540s | 8,858 | 38.7 ms | 78.4 ms | 126.4 ms |

Throughput held between 8,858 and 10,432 spans/sec across the ten windows — flat, with no downward
trend as the database filled and pruned. The final window is the outlier: throughput 12% below the
run median and p95 up from ~49 ms to 78 ms. **We did not identify the cause**, and on a laptop
that is also running other applications the honest answer is that we cannot rule out the machine
rather than the server.

Alongside it, sampled every 30 s (21 samples): server RSS stayed between **92 MB and 105 MB** under
load with no upward trend, and fell back to **15 MB** within 30 s of the load stopping. `/healthz`
reported `queue_depth: 0`, `lag_seconds: 0.0`, `shed: 0` and `quarantined: 0` at **every** sample.

Ten minutes is a soak, not an endurance test. It rules out fast leaks and immediate degradation.
It says nothing about day-scale behaviour.

### What the durability spool costs

`services/spool.py` fsyncs each batch to disk before the request is acknowledged. Three runs each,
same box, same config, only `SPOOL_ENABLED` differing:

| `SPOOL_ENABLED` | spans/sec (3 runs) | p50 | p95 |
|---|---|---|---|
| `true` (default) | 10,325 / 10,289 / 10,242 | ~36.6 ms | ~48.7 ms |
| `false` | 10,870 / 10,483 / 10,555 | ~35.4 ms | ~46.2 ms |

**~2.5% throughput and about 1 ms of p50** to guarantee that an accepted batch survives a database
outage. Leave it on.

### What retention pruning costs (on SQLite: nothing)

| `RUNS_RETENTION` | spans/sec (3 runs) | p50 |
|---|---|---|
| `10000` (default, pruning every batch) | 10,325 / 10,289 / 10,242 | ~36.6 ms |
| `0` (off, table grows unbounded) | 9,443 / 9,648 / 9,549 | ~41.3 ms |

Pruning is *not* the expensive part on SQLite — the run with pruning **off** was slightly slower,
because its table grew to ~190k rows during the run while the pruned one stayed at 10k. Hold onto
this result; Postgres behaves very differently.

### More uvicorn workers on SQLite: don't

`--workers 4`, same SQLite file, three 20 s runs:

| Run | spans/sec | p50 | p99 | max | 503s |
|---|---|---|---|---|---|
| 1 | 8,222 | 25.5 ms | 288.9 ms | 1,433 ms | 2 |
| 2 | 10,439 | 28.3 ms | 156.8 ms | 287 ms | 0 |
| 3 | 12,332 | 17.3 ms | 264.4 ms | 874 ms | 1 |

Median throughput is roughly unchanged, the p99 is 3-5x worse, the max hits 1.4 s, and three
batches came back **503** — from `sqlite3.OperationalError: database is locked` after the 5 s
`busy_timeout`, not from backpressure (`/healthz` showed `shed: 0`). Those batches stayed spooled;
the drainer logged replays (`drained N staged ingest batch(es)`) and `queue_depth` was back to 0 by
the end of the run — the spool doing its job — but the exporter still had to retry. Startup also
races: the Alembic advisory lock is Postgres-only, so the four workers logged
`table users already exists` while racing `upgrade head`.

**One SQLite writer, one worker.** Multiple workers is a Postgres configuration.

---

## What the stock config actually allows

Everything at defaults — including `INGEST_RATE_PER_MIN=600` — 4 exporters, 100 spans/batch:

```
spans/sec     1132.9   (11.33 batches/sec, 22700 spans accepted)
latency ms    p50 41.27  p95 58.32  p99 68.05   (accepted batches only)
requests      11182 total / 227 ok / 10955 429 / 0 503 / 0 errors
rates         rate-limited 97.97%
```

The limit is **600 requests per project per minute**, not per span, so what you get depends
entirely on batch size:

| Spans/batch at the 600 req/min default | Ceiling |
|---|---|
| 10 | ~100 spans/sec |
| 100 | ~1,000 spans/sec |
| 500 | ~5,000 spans/sec |

This is a per-project burst guard, and for most agent workloads it never binds. If you are
ingesting from a fleet, raise `INGEST_RATE_PER_MIN` deliberately — and note that without
`REDIS_URL` the counter is **per worker process**, so N workers means N times the limit.

A 429 is retriable and OTLP exporters retry it, but the ProveKit SDK's exporter treats a rejected
export as a failure and buffers it; sustained 429s mean spans arriving late, not never.

---

## Postgres: measured, not publishable

Same harness, same box, PostgreSQL 16.14 (`postgres:16-alpine`) in a container on Docker Engine
29.5.3 — i.e. inside Docker Desktop's macOS VM — reached over the published port (`SELECT 1` round
trip through it: **0.119 ms**). Stock image settings —
`shared_buffers 128MB`, `fsync on`, `synchronous_commit on`.

| Config | spans/sec (3 runs) | p50 | p95 |
|---|---|---|---|
| 1 worker, `RUNS_RETENTION=10000` | 1,724 / 2,864 / 4,060 | 230 / 108 / 89 ms | 322 / 329 / 127 ms |
| 4 workers, `RUNS_RETENTION=10000` | 2,275 / 5,229 / 3,117 | 134 / 45 / 107 ms | 278 / 288 / 231 ms |
| 1 worker, `RUNS_RETENTION=0` | 5,131 / 5,108 / 4,861 | 75 / 75 / 78 ms | 114 / 119 / 120 ms |

**Do not quote the first two rows as a Postgres capability.** A 2.4x spread between repeats of the
same run is not a measurement, and two effects are tangled up in it:

1. **Docker Desktop on macOS is a VM.** Postgres here is virtualized storage and networking on the
   same laptop that is running both the server and the load generator. A real Postgres host shares
   none of that.
2. **Retention pruning bloats the table, and stock autovacuum cannot keep up.** After the pruned
   runs, `pg_stat_user_tables` showed **181,904 dead tuples** against 4,700 live rows, from 404,639
   inserts and 392,500 deletes, with **one** autovacuum in the entire run. With `RUNS_RETENTION=0`
   the same box was stable at ~5,000 spans/sec with **zero** dead tuples and a p95 of ~118 ms.

The third row is the honest one: this Postgres, on this laptop, did ~5,000 spans/sec repeatably.
We did not profile where the remaining time goes, and we have not measured Postgres on real server
hardware at all.

**The one transferable finding:** if you self-host on Postgres with `RUNS_RETENTION` set, the
`runs` table takes a delete for every insert at steady state. Tune autovacuum for it
(`ALTER TABLE runs SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_vacuum_cost_delay = 0)`
or similar) and watch `n_dead_tup`. Everything else on this page about Postgres is about a laptop
VM.

---

## Backpressure and shedding

Ingest has three ways to refuse a batch. This test bed exercised two of them, and the one people
worry about most never fired:

| Signal | Meaning | Seen in these runs |
|---|---|---|
| `503` + `Retry-After: 5` from `_check_ingest_backpressure` | `spool.depth() >= SPOOL_MAX_DEPTH` (5000) — the database is far behind | **Never.** `queue_depth` stayed 0; entries were released as fast as they were staged |
| `503 ingest temporarily unavailable` from a failed persist | The write failed; the batch stays spooled for the drainer | Only on **SQLite with 4 workers** (`database is locked`): 4 in that config's server log, 3 of them inside a measured window |
| `429` | Per-project ingest rate limit | Only when `INGEST_RATE_PER_MIN` was left at its default |

Backpressure engages when writes fail or stall, not when traffic is merely heavy: at 10k spans/sec
sustained, every `queue_depth` sample we took — before and after each run, and every 30 s through
the soak — was **0**. To see the shed path you have to break the database, not flood it.
`/healthz` exposes `queue_depth`, `lag_seconds`, `shed` and `quarantined`; watch `lag_seconds`, a
climbing value is the earliest honest signal that ingest is behind.

> Observed, not fixed: with 4 workers sharing one `SPOOL_DIR`, the `quarantined` counter rose to
> 4-6 even though no batch was corrupt. The logs show `corrupt spool entry … No such file or
> directory` — one worker's drainer opening an entry another worker had already released. The data
> is fine (the other worker committed it); the counter over-reports. Treat `quarantined` on a
> multi-worker deployment as approximate.

---

## Reproducing this

```bash
# 1. a server whose config you know (from backend/)
DATABASE_URL="sqlite:///./loadtest.db" INGEST_RATE_PER_MIN=0 SECRET_KEY=<something-long> \
  ./venv/bin/python -m uvicorn provekit.main:app --port 8011

# 2. drive it, from the repo root (mints its own throwaway account + key on a local instance)
./backend/venv/bin/python testkit/loadtest.py \
  --endpoint http://localhost:8011 --bootstrap \
  --concurrency 4 --batch-size 100 --duration 20 --warmup 5 \
  --label "sqlite, 1 worker, <your hardware>" --json result.json
```

The harness is stdlib-only, so it also runs from a machine that has nothing installed:

```bash
PROVEKIT_API_KEY=pk_... python testkit/loadtest.py --endpoint https://your-instance --duration 60
```

See [`testkit/README.md`](../testkit/README.md#load-testing-your-instance) for every flag and for
the rules on what a result may and may not be labelled.

---

## What these numbers do not tell you

- **Nothing about your hardware.** A laptop core is not a server core, and this page contains no
  extrapolation to one. Run the harness on your box; it takes 30 seconds.
- **Nothing about Postgres capacity.** See above — the only stable Postgres number here came from a
  Docker Desktop VM sharing a laptop with its own client.
- **Nothing about the read path.** Dashboards, trace queries, search and rollups were idle
  throughout. A production instance serves reads against the same core the ingest is saturating.
- **Nothing about multi-tenant behaviour.** One project, one key. Rate limits, quotas and retention
  are all per-project or per-account.
- **Nothing about redaction.** `REDACT_PII` was off; it adds regex passes over every span payload.
- **Nothing about durability under real failure.** The spool drained to `queue_depth: 0` after the
  batches that 503'd, and the drainer logged the replays — but we did not reconcile span-by-span
  that every accepted span is present. That is a distinct test, and it isn't this one.
- **Nothing about sustained load beyond 10 minutes.** The soak above is 10 minutes, not 10 hours.
