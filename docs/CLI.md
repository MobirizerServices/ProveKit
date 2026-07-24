# `provekit` — the command line

Everything the portal shows sits behind a key-authed HTTP API, so anything you can click you
should be able to script. `provekit` is that surface: list yesterday's failures from a cron
job, seed a dataset from a fixture file, gate a deploy on an evaluation.

It is an **API client, not a second server**. It talks to the documented `/v1` endpoints with
a project key and never imports the app or opens a database, so the same command works
against `localhost:8000` and against a portal three regions away.

```
  your shell / CI                  portal
  provekit ──Bearer pk_…──▶ /v1/traces, /v1/datasets, /v1/experiments (HTTP)
```

## Install and configure

```bash
pip install provekit                                 # core only — the CLI needs httpx, nothing else
export PROVEKIT_API_KEY=pk_...                       # a project key from the portal (API keys)
export PROVEKIT_ENDPOINT=https://provekit.your-co.com
provekit traces list
```

The same two variables the SDK reads. `--api-key` / `--endpoint` override them per command,
which is how you point one shell at two portals.

Every command prints a table for humans and takes `--json` for machines, and exits **non-zero**
when the thing you asked for did not happen — so `set -e` in a CI job means what it says.

| Exit code | Meaning |
|---|---|
| `0` | It worked. |
| `1` | Config missing, portal unreachable, a 4xx/5xx, or an `eval run` gate tripped. |
| `2` | You typed the command wrong (argparse usage error). |
| `3` | `eval run --baseline` **refused to judge** — the dataset changed between the two runs, so the delta means nothing. Deliberately not `1`: "your change made it worse" and "I can't tell" call for different reactions. |

## Commands

### `provekit traces list`

Recent runs, newest first.

```bash
provekit traces list                                  # last 20
provekit traces list --status failed --since 24h      # what broke yesterday
provekit traces list --limit 200 --json | jq '.[].trace_id'
```

```
TRACE             STATUS     LABEL          DURATION  SPANS  TOKENS  CREATED
e02bab6287801ae8  failed     flaky-agent    2ms       2      0       2026-07-22T05:02:13
0f907c5c32328c24  completed  support-agent  15ms      2      75      2026-07-22T05:02:13
```

| Flag | |
|---|---|
| `--status` | `failed`, `completed` — anything the API stores. |
| `--limit` | Default 20; the server caps it at 200. |
| `--since` | `90m`, `24h`, `7d`. Rounded **up** to whole hours, because the API's window is hourly and `--since 30m` must not truncate to "no window at all". |
| `--json` | The raw `/v1/traces` payload, unmodified. |

### `provekit traces get <trace_id>`

The full span tree, rebuilt from `parent_span_id` exactly as the portal does. `x` marks a
failed span; errors print under the span that raised them.

```
$ provekit traces get e02bab6287801ae885229e6e90f0e583
x flaky-agent [agent] 2ms
    error: RuntimeError: upstream billing_api returned 503
  x call-upstream [tool] 2ms
      error: RuntimeError: upstream billing_api returned 503
```

A trace whose root span never arrived — the process died before the root ended, so nothing
was exported for it — still prints its spans, flat, instead of an empty tree.

### `provekit datasets list | create | add`

```bash
provekit datasets create qa-golden --description "regression set"
provekit datasets add qa-golden --input "refund my order" --expected "refund started"
provekit datasets add qa-golden --file items.jsonl      # bulk
provekit datasets list
```

`add` takes a dataset **id or name**, so a CI script never has to hardcode an id. `--file`
is JSONL — one `{"input": …, "expected": …, "meta": {…}}` object per line, not a JSON array,
so a fixture file can be appended to and reviewed a line at a time.

> **Dataset writes and hosted portals.** `/v1/datasets` is read-only: `pk.evaluate()` only
> ever needed to *pull* items, so creating a dataset lives on the portal's session-authed
> `/api` router. `create` and `add` therefore try `/v1` first and fall back to `/api`, which a
> self-hosted (non-hosted) instance resolves to the default project. Against a hosted portal,
> where a project key is not a session, the fallback is refused and the CLI says so — create
> the dataset in the UI, then `list` / `eval run` from CI as normal. When the server grows
> `POST /v1/datasets`, the fallback stops being reached and nothing here changes.

### `provekit eval run`

Score a target over a dataset, record it as an experiment in the portal, and optionally fail
the build.

```bash
provekit eval run \
  --dataset qa-golden \
  --command "python my_agent.py" \
  --scorer exact_match --scorer contains \
  --name "pr-${GITHUB_SHA::7}" \
  --fail-under 0.8
```

The target is a **command**, not a Python callable: `pk.evaluate()` and the
[eval GitHub Action](CI_GATE.md) already cover a Python target, and a subprocess is what a CLI
can offer that neither can — a target in any language. Each item's `input` arrives on the
target's **stdin**; its **stdout** is the output. A non-zero exit or a `--timeout` overrun is
recorded as an `ERROR: …` output and scored like any other, because one failing example is a
data point, not a reason to abandon the run.

| Flag | |
|---|---|
| `--dataset` | Dataset id or name. |
| `--command` | The target. Run through your shell, so pipes and `$VARS` work. |
| `--scorer` | Repeatable. `exact_match`, `contains`, `regex_match`, `json_valid`. Defaults to `exact_match`. |
| `--name` | Experiment name in the portal (default `cli-eval`). |
| `--timeout` | Per-item target timeout, seconds (default 60). |
| `--fail-under` | Exit 1 if `mean_score` drops below this. A missing score counts as a failure, not a pass. An absolute floor. |
| `--baseline` | Experiment id to gate against. Exits 1 only if a regression is **statistically real**, using the same paired test the portal shows — a dip within noise passes and says so. Exits 3 if the dataset changed between the runs. |
| `--allow-incomparable` | Gate anyway when the dataset changed, instead of exiting 3. |

```
Experiment 7 — pr-a1b2c3d
3 results
  contains: 0.667
  exact_match: 0.667
  mean_score: 0.667
```

**Gating on significance.** A threshold gate fails on chance: run an unchanged model over
twenty examples twice and the mean moves a couple of points either way. `--baseline` asks
whether the move is bigger than chance explains.

```bash
provekit eval run --dataset regression-set --command "python agent.py" --baseline 196
```

```text
acc moved -0.040 — within noise (p=0.420, n=20); not blocking
provekit: no significant regression against experiment 196.
```

The two flags compose, and answer different questions: `--fail-under` is *never ship below
this*, `--baseline` is *don't ship a real regression*. See [CI_GATE.md](CI_GATE.md).

### `provekit up`

Run ProveKit locally with one command — the API, plus the portal when you are in a checkout
with its dependencies installed.

```bash
provekit up                       # API on :8000, portal on :3000
provekit up --no-frontend         # API only
provekit up --port 9000
```

```text
  API     http://127.0.0.1:8000
  Portal  http://localhost:3000

  Local mode needs no login. Ctrl-C to stop.
```

It waits for `/healthz` to answer before printing the URL — a URL that 404s for another two
seconds is how a first run gets written off as broken — and shuts both processes down on
Ctrl-C. Needs the server extra (`pip install "provekit[server]"`); without it the command says
so by name, and the read-only commands above keep working against a remote portal.

The summary is printed (and flushed) *before* the threshold verdict goes to stderr, so a
failing gate in a piped CI log never appears above the numbers that explain it.

### `provekit doctor`

The same diagnostic as the standalone `provekit-doctor`, reached from the one command:

```bash
provekit doctor          # why aren't traces arriving?
provekit doctor --send   # ...and post one probe span
```

It reads the environment itself and exits 1 on a `FAIL` row. See
[DEBUGGING.md](DEBUGGING.md).

## In CI

```yaml
- name: Eval gate
  env:
    PROVEKIT_API_KEY: ${{ secrets.PROVEKIT_API_KEY }}
    PROVEKIT_ENDPOINT: ${{ secrets.PROVEKIT_ENDPOINT }}
  run: |
    pip install provekit
    provekit eval run --dataset qa-golden --command "python eval/target.py" \
      --scorer exact_match --fail-under 0.8
```

```bash
# a nightly failure digest
provekit traces list --status failed --since 24h --json \
  | jq -r '.[] | "\(.trace_id)\t\(.label)"'
```

## Related

- [MCP.md](MCP.md) — the same read API, exposed to an assistant instead of a shell.
- [EVALUATION.md](EVALUATION.md) — `pk.evaluate()`, the in-process equivalent of `eval run`.
- [CI_GATE.md](CI_GATE.md) — the GitHub Action, for a Python target and PR comments.
- [API.md](API.md) — the endpoints underneath all of this.
