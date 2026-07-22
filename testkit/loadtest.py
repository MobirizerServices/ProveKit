#!/usr/bin/env python3
"""OTLP ingest load harness for a running ProveKit.

Drives real `POST /v1/traces` requests with a real project key. It deliberately does *not*
import the server or call `services.otel` directly: the number people want is what a
self-hosted box accepts over HTTP, which includes auth, rate limits, JSON parsing, the
disk fsync in `services/spool.py`, the insert, and retention pruning. A harness that skips
the transport measures a function, not a deployment.

Stdlib only (`http.client` + threads) so it runs against a remote instance from a machine
that has nothing installed. One persistent connection per worker: a fresh TCP (and TLS)
handshake per batch would put connection setup inside the latency we are attributing to
ingest.

Closed loop by default — N workers, each sending its next batch only once the previous one
is acknowledged. That is how an OTLP BatchSpanProcessor behaves (one in-flight export per
process), and it means the reported latency is service time at that concurrency, not a
queueing delay we manufactured. `--target-rps` switches to a paced/open loop when you want
to hold offered load fixed and watch latency degrade instead.

Usage:

    # against a local dev server (make backend), minting its own throwaway account + key
    python testkit/loadtest.py --endpoint http://localhost:8000 --bootstrap --duration 30

    # against an instance you already have a key for
    PROVEKIT_API_KEY=pk_... python testkit/loadtest.py \
        --endpoint https://provekit.example.com --concurrency 8 --duration 60

Every number it prints is from the run it just did. Nothing here extrapolates.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import secrets
import statistics
import sys
import threading
import time
from urllib.parse import urlparse

# Batch bodies are capped server-side by MAX_BODY_BYTES (default 2 MB). We warn rather than
# silently generate batches the server will reject with 413, which would read as an ingest
# failure rather than a harness mistake.
DEFAULT_MAX_BODY_BYTES = 2_000_000


# ---------------------------------------------------------------- payload generation

def _hex(n_bytes: int) -> str:
    return secrets.token_hex(n_bytes)


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": value}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _filler(n: int, rng: random.Random) -> str:
    """Prompt/completion-shaped text of a given length.

    Real spans carry payloads, and payload size drives JSON parsing, the spool write and the
    row size — the three things that actually cost. Benchmarking with empty attributes would
    report a throughput nobody can reproduce with real traffic.
    """
    words = ("retrieve", "summarise", "the", "customer", "invoice", "for", "quarter",
             "and", "explain", "any", "discrepancy", "in", "plain", "language")
    out = []
    total = 0
    while total < n:
        w = rng.choice(words)
        out.append(w)
        total += len(w) + 1
    return " ".join(out)[:n]


def make_trace(spans_per_trace: int, span_bytes: int, rng: random.Random) -> list[dict]:
    """One agent trace: a root agent span with alternating llm/tool children.

    Shaped like what `services/otel.py` classifies in production (gen_ai.* v1.37 dialect,
    parent/child ids, token usage) so the ingest does the same work it does for real traffic.
    """
    now_ns = time.time_ns()
    trace_id = _hex(16)
    root_id = _hex(8)
    spans = [{
        "name": "agent.run",
        "traceId": trace_id,
        "spanId": root_id,
        "parentSpanId": "",
        "startTimeUnixNano": str(now_ns - 900_000_000),
        "endTimeUnixNano": str(now_ns),
        "status": {"code": 1},
        "attributes": [
            _attr("gen_ai.operation.name", "invoke_agent"),
            _attr("gen_ai.agent.name", "loadtest-agent"),
            _attr("gen_ai.input.messages", _filler(span_bytes, rng)),
        ],
    }]
    for i in range(max(0, spans_per_trace - 1)):
        is_llm = i % 2 == 0
        start = now_ns - 800_000_000 + i * 10_000_000
        span = {
            "name": "chat gpt-4o-mini" if is_llm else "tool.lookup",
            "traceId": trace_id,
            "spanId": _hex(8),
            "parentSpanId": root_id,
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(start + 250_000_000),
            "status": {"code": 1},
            "attributes": [],
        }
        if is_llm:
            span["attributes"] = [
                _attr("gen_ai.operation.name", "chat"),
                _attr("gen_ai.provider.name", "openai"),
                _attr("gen_ai.request.model", "gpt-4o-mini"),
                _attr("gen_ai.usage.input_tokens", rng.randint(200, 900)),
                _attr("gen_ai.usage.output_tokens", rng.randint(20, 300)),
                _attr("gen_ai.input.messages", _filler(span_bytes, rng)),
                _attr("gen_ai.output.messages", _filler(span_bytes // 2, rng)),
            ]
        else:
            span["attributes"] = [
                _attr("gen_ai.operation.name", "execute_tool"),
                _attr("gen_ai.tool.name", "lookup_invoice"),
                _attr("gen_ai.tool.call.arguments", _filler(span_bytes // 4, rng)),
            ]
        spans.append(span)
    return spans


def make_batch(batch_size: int, spans_per_trace: int, span_bytes: int,
               rng: random.Random) -> bytes:
    """One OTLP ExportTraceServiceRequest body of exactly `batch_size` spans."""
    spans: list[dict] = []
    while len(spans) < batch_size:
        spans.extend(make_trace(spans_per_trace, span_bytes, rng))
    spans = spans[:batch_size]
    body = {"resourceSpans": [{
        "resource": {"attributes": [_attr("service.name", "provekit-loadtest")]},
        "scopeSpans": [{"scope": {"name": "provekit.loadtest"}, "spans": spans}],
    }]}
    return json.dumps(body).encode()


# ---------------------------------------------------------------- HTTP plumbing

def _connect(url: str, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    """A keep-alive connection to the instance, plus the path prefix to prepend to routes."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    return conn, parsed.path.rstrip("/")


def _request(conn, method: str, path: str, body: bytes | None, headers: dict):
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    payload = resp.read()          # must drain, or the connection can't be reused
    return resp.status, dict(resp.getheaders()), payload


# ---------------------------------------------------------------- bootstrap / health

def bootstrap_key(endpoint: str, timeout: float = 10.0) -> str:
    """Register a throwaway account on the target and mint a project key from it.

    Only for a local instance you own — it creates a real account. It exists so a laptop run
    is a single command, and so the numbers in docs/PERFORMANCE.md are reproducible without a
    manual setup step that people would skip and then quote the number anyway.
    """
    conn, prefix = _connect(endpoint, timeout)
    # Not a .local/.test/.invalid address: the register endpoint validates with EmailStr, which
    # rejects special-use domains outright.
    email = f"loadtest+{secrets.token_hex(6)}@loadtest.provekit.dev"
    password = secrets.token_urlsafe(16)
    status, headers, body = _request(
        conn, "POST", f"{prefix}/api/auth/register",
        json.dumps({"email": email, "password": password, "name": "loadtest"}).encode(),
        {"Content-Type": "application/json"})
    if status >= 400:
        raise SystemExit(f"bootstrap: register failed ({status}): {body[:200]!r}")
    cookie = headers.get("set-cookie", "").split(";")[0]
    if not cookie:
        raise SystemExit("bootstrap: no session cookie returned by /api/auth/register")
    status, _, body = _request(
        conn, "POST", f"{prefix}/api/api-keys", json.dumps({"name": "loadtest"}).encode(),
        {"Content-Type": "application/json", "Cookie": cookie})
    if status >= 400:
        raise SystemExit(f"bootstrap: key creation failed ({status}): {body[:200]!r}")
    conn.close()
    key = json.loads(body).get("key")
    if not key:
        raise SystemExit("bootstrap: key creation returned no plaintext key")
    return key


def probe_health(endpoint: str, timeout: float = 10.0) -> dict:
    """`/healthz` — carries the spool depth, lag and shed/quarantine counters, which are the
    backpressure state we want on both sides of the run."""
    try:
        conn, prefix = _connect(endpoint, timeout)
        _, _, body = _request(conn, "GET", f"{prefix}/healthz", None, {})
        conn.close()
        return json.loads(body)
    except Exception as exc:            # a health probe must never fail the run
        return {"error": str(exc)}


# ---------------------------------------------------------------- the load loop

class Tally:
    """Per-worker counters. Kept thread-local and merged at the end so the hot loop never
    contends on a lock — a lock in the send path would show up in the latency we report."""

    def __init__(self) -> None:
        # Accepted-batch latency is kept apart from everything-else latency on purpose. A 429
        # or a backpressure 503 is refused before any work happens, so folding those samples in
        # makes an overloaded server look *faster* the more it rejects. The headline percentiles
        # are the ones for batches that actually landed.
        self.latencies_ms: list[float] = []
        self.all_latencies_ms: list[float] = []
        # (seconds since measurement start, latency, accepted?) per request. An aggregate over a
        # long run can't tell a steady 10k spans/sec from one that started at 15k and decayed to
        # 5k, which is the only question a soak exists to answer.
        self.samples: list[tuple[float, float, bool]] = []
        self.ok = 0
        self.spans_accepted = 0
        self.rate_limited = 0     # 429 — the project ingest rate limit
        self.shed = 0             # 503 — spool backpressure or a failed persist
        self.other_http = 0
        self.errors = 0           # transport-level: reset, timeout, refused
        self.status_codes: dict[int, int] = {}
        self.bytes_sent = 0

    def merge(self, other: "Tally") -> None:
        self.latencies_ms += other.latencies_ms
        self.all_latencies_ms += other.all_latencies_ms
        self.samples += other.samples
        self.ok += other.ok
        self.spans_accepted += other.spans_accepted
        self.rate_limited += other.rate_limited
        self.shed += other.shed
        self.other_http += other.other_http
        self.errors += other.errors
        self.bytes_sent += other.bytes_sent
        for code, n in other.status_codes.items():
            self.status_codes[code] = self.status_codes.get(code, 0) + n


def _worker(args, key: str, stop_at: float, warmup_until: float, tally: Tally,
            seed: int, pacer: "_Pacer | None") -> None:
    rng = random.Random(seed)
    conn, prefix = _connect(args.endpoint, args.timeout)
    path = f"{prefix}/v1/traces"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # Bodies are regenerated every request so no two batches share span ids: identical ids
    # would hit the (trace_id, span_id) dedupe in _persist_spans and we'd be timing a no-op.
    while time.monotonic() < stop_at:
        if pacer is not None and not pacer.wait(stop_at):
            break
        body = make_batch(args.batch_size, args.spans_per_trace, args.span_bytes, rng)
        counted = time.monotonic() >= warmup_until
        t0 = time.perf_counter()
        try:
            status, _, _ = _request(conn, "POST", path, body, headers)
        except Exception:
            # Rebuild the connection: a reset mid-run must not turn every later request into
            # an error and depress the throughput number for a reason that isn't the server's.
            try:
                conn.close()
            except Exception:
                pass
            conn, _ = _connect(args.endpoint, args.timeout)
            if counted:
                tally.errors += 1
            continue
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if not counted:
            continue
        tally.all_latencies_ms.append(elapsed_ms)
        tally.samples.append((time.monotonic() - warmup_until, elapsed_ms, status == 200))
        tally.bytes_sent += len(body)
        tally.status_codes[status] = tally.status_codes.get(status, 0) + 1
        if status == 200:
            tally.latencies_ms.append(elapsed_ms)
            tally.ok += 1
            tally.spans_accepted += args.batch_size
        elif status == 429:
            tally.rate_limited += 1
        elif status == 503:
            tally.shed += 1
        else:
            tally.other_http += 1
    try:
        conn.close()
    except Exception:
        pass


class _Pacer:
    """Open-loop pacing: hands out send slots at a fixed rate regardless of how slow the
    server is, so offered load stays constant and latency is allowed to blow up. Closed-loop
    (the default) can't show that — it self-throttles."""

    def __init__(self, rps: float) -> None:
        self._interval = 1.0 / rps
        self._next = time.monotonic()
        self._lock = threading.Lock()

    def wait(self, stop_at: float) -> bool:
        with self._lock:
            slot = self._next
            self._next += self._interval
        delay = slot - time.monotonic()
        if slot >= stop_at:
            return False
        if delay > 0:
            time.sleep(delay)
        return True


def intervals(samples: list[tuple[float, float, bool]], batch_size: int,
              width: float) -> list[dict]:
    """Bucket the run into fixed windows so drift is visible.

    A soak's whole value is the shape over time — memory pressure, a growing table, autovacuum
    falling behind and a spool that stops draining all look identical in a single average.

    The trailing partial window is dropped: a bucket that only ran for part of `width` would
    report a throughput dip that is arithmetic, not the server slowing down.
    """
    if not samples or width <= 0:
        return []
    buckets: dict[int, list[tuple[float, bool]]] = {}
    for t_rel, ms, accepted in samples:
        buckets.setdefault(int(t_rel // width), []).append((ms, accepted))
    last_complete = int(max(t / width for t, _, _ in samples)) - 1
    out = []
    for idx in sorted(b for b in buckets if b <= last_complete):
        rows = buckets[idx]
        lat = sorted(ms for ms, accepted in rows if accepted)
        accepted_n = sum(1 for _, accepted in rows if accepted)
        out.append({
            "from_s": round(idx * width, 1),
            "spans_per_sec": round(accepted_n * batch_size / width, 1),
            "p50": round(percentile(lat, 50), 2),
            "p95": round(percentile(lat, 95), 2),
            "p99": round(percentile(lat, 99), 2),
            "refused": len(rows) - accepted_n,
        })
    return out


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile. No interpolation: with a few thousand samples the difference
    is noise, and nearest-rank is a latency actually observed rather than a synthesized one."""
    if not sorted_values:
        return 0.0
    k = max(1, int(round(p / 100.0 * len(sorted_values))))
    return sorted_values[min(k, len(sorted_values)) - 1]


# ---------------------------------------------------------------- reporting

def summarize(args, tally: Tally, wall_seconds: float, health_before: dict,
              health_after: dict, key_source: str) -> dict:
    lat = sorted(tally.latencies_ms)
    lat_all = sorted(tally.all_latencies_ms)
    requests = tally.ok + tally.rate_limited + tally.shed + tally.other_http + tally.errors
    return {
        "config": {
            "endpoint": args.endpoint,
            "label": args.label,
            "concurrency": args.concurrency,
            "batch_size": args.batch_size,
            "spans_per_trace": args.spans_per_trace,
            "span_bytes": args.span_bytes,
            "duration_s": args.duration,
            "warmup_s": args.warmup,
            "target_rps": args.target_rps,
            "interval": args.interval,
            "key_source": key_source,
        },
        "wall_seconds": round(wall_seconds, 3),
        "requests": {
            "total": requests,
            "ok": tally.ok,
            "rate_limited_429": tally.rate_limited,
            "shed_503": tally.shed,
            "other_http": tally.other_http,
            "transport_errors": tally.errors,
            "status_codes": tally.status_codes,
        },
        "throughput": {
            "spans_per_sec": round(tally.spans_accepted / wall_seconds, 1) if wall_seconds else 0,
            "batches_per_sec": round(tally.ok / wall_seconds, 2) if wall_seconds else 0,
            "spans_accepted": tally.spans_accepted,
            "mb_sent": round(tally.bytes_sent / 1_000_000, 2),
        },
        "latency_ms": {
            "samples": len(lat),
            "mean": round(statistics.fmean(lat), 2) if lat else 0,
            "p50": round(percentile(lat, 50), 2),
            "p95": round(percentile(lat, 95), 2),
            "p99": round(percentile(lat, 99), 2),
            "max": round(lat[-1], 2) if lat else 0,
        },
        "latency_all_ms": {          # includes refused batches (429/503), which return early
            "samples": len(lat_all),
            "p50": round(percentile(lat_all, 50), 2),
            "p95": round(percentile(lat_all, 95), 2),
            "p99": round(percentile(lat_all, 99), 2),
        },
        "rates": {
            "error_rate": round((tally.errors + tally.other_http) / requests, 4) if requests else 0,
            "shed_rate": round(tally.shed / requests, 4) if requests else 0,
            "rate_limited_rate": round(tally.rate_limited / requests, 4) if requests else 0,
        },
        "intervals": intervals(tally.samples, args.batch_size, args.interval),
        "spool": {"before": health_before.get("ingest"), "after": health_after.get("ingest")},
    }


def print_report(r: dict) -> None:
    c, t, lat = r["config"], r["throughput"], r["latency_ms"]
    req, rates = r["requests"], r["rates"]
    print()
    print("ProveKit ingest load test")
    print(f"  target        {c['endpoint']}  [{c['label'] or 'unlabelled'}]")
    print(f"  load          {c['concurrency']} exporters x {c['batch_size']} spans/batch, "
          f"{c['spans_per_trace']} spans/trace, {c['span_bytes']}B payload attrs")
    print(f"  duration      {r['wall_seconds']}s wall (+{c['warmup_s']}s warmup discarded)")
    print()
    print(f"  spans/sec     {t['spans_per_sec']}   ({t['batches_per_sec']} batches/sec, "
          f"{t['spans_accepted']} spans accepted, {t['mb_sent']} MB sent)")
    print(f"  latency ms    p50 {lat['p50']}  p95 {lat['p95']}  p99 {lat['p99']}  "
          f"max {lat['max']}  (accepted batches only, n={lat['samples']})")
    if r["latency_all_ms"]["samples"] != lat["samples"]:
        alat = r["latency_all_ms"]
        print(f"  incl. refused p50 {alat['p50']}  p95 {alat['p95']}  p99 {alat['p99']}  "
              f"(n={alat['samples']}) — refused batches return before doing work")
    print(f"  requests      {req['total']} total / {req['ok']} ok / "
          f"{req['rate_limited_429']} 429 / {req['shed_503']} 503 / "
          f"{req['other_http']} other / {req['transport_errors']} transport errors")
    print(f"  rates         error {rates['error_rate']:.2%}  shed {rates['shed_rate']:.2%}  "
          f"rate-limited {rates['rate_limited_rate']:.2%}")
    if len(r["intervals"]) > 1:
        print()
        print(f"  per {c['interval']:.0f}s window (drift is what a long run is for):")
        for b in r["intervals"]:
            print(f"    t+{b['from_s']:>6.0f}s  {b['spans_per_sec']:>9.1f} spans/sec  "
                  f"p50 {b['p50']:>7.2f}  p95 {b['p95']:>7.2f}  p99 {b['p99']:>7.2f}  "
                  f"refused {b['refused']}")
        print()
    print(f"  spool before  {r['spool']['before']}")
    print(f"  spool after   {r['spool']['after']}")
    if req["rate_limited_429"] > req["total"] * 0.01:
        print()
        print("  NOTE: 429s present — you measured the per-project ingest rate limit "
              "(INGEST_RATE_PER_MIN, default 600 req/min), not ingest capacity.")
    if req["transport_errors"] or req["other_http"]:
        print()
        print("  NOTE: transport/other-HTTP errors present — the throughput above is a "
              "degraded-path number. Say so wherever you quote it.")
    print()


# ---------------------------------------------------------------- entrypoint

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--endpoint", default=os.environ.get("PROVEKIT_ENDPOINT", "http://localhost:8000"),
                   help="base URL of the ProveKit instance (default $PROVEKIT_ENDPOINT or :8000)")
    p.add_argument("--key", default=os.environ.get("PROVEKIT_API_KEY", ""),
                   help="project key (pk_...). Default $PROVEKIT_API_KEY")
    p.add_argument("--bootstrap", action="store_true",
                   help="register a throwaway account on the target and mint a key (local only)")
    p.add_argument("--concurrency", type=int, default=4, help="concurrent exporters (default 4)")
    p.add_argument("--batch-size", type=int, default=100, help="spans per POST (default 100)")
    p.add_argument("--spans-per-trace", type=int, default=10,
                   help="spans per synthetic trace (default 10)")
    p.add_argument("--span-bytes", type=int, default=400,
                   help="approx bytes of prompt/completion text per span (default 400)")
    p.add_argument("--duration", type=float, default=30.0, help="measured seconds (default 30)")
    p.add_argument("--warmup", type=float, default=5.0,
                   help="seconds of load discarded before measuring (default 5)")
    p.add_argument("--target-rps", type=float, default=0.0,
                   help="paced open-loop batches/sec across all workers (0 = closed loop)")
    p.add_argument("--interval", type=float, default=60.0,
                   help="width in seconds of the per-window drift breakdown (default 60)")
    p.add_argument("--timeout", type=float, default=30.0, help="per-request timeout seconds")
    p.add_argument("--label", default="",
                   help="what this run is (e.g. 'sqlite-wal, 1 uvicorn worker') — copied into "
                        "the report, because a number without its conditions is unusable")
    p.add_argument("--json", dest="json_out", default="",
                   help="also write the full result as JSON to this path")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.endpoint = args.endpoint.rstrip("/")
    if args.bootstrap:
        key, key_source = bootstrap_key(args.endpoint, args.timeout), "bootstrap"
    elif args.key:
        key, key_source = args.key, "provided"
    else:
        print("error: pass --key / $PROVEKIT_API_KEY, or --bootstrap for a local instance",
              file=sys.stderr)
        return 2

    sample = make_batch(args.batch_size, args.spans_per_trace, args.span_bytes, random.Random(0))
    if len(sample) > DEFAULT_MAX_BODY_BYTES:
        print(f"warning: batch body is {len(sample)} bytes, above the default "
              f"MAX_BODY_BYTES ({DEFAULT_MAX_BODY_BYTES}); expect 413s", file=sys.stderr)
    print(f"batch body ~{len(sample) / 1000:.1f} kB for {args.batch_size} spans; "
          f"warming up {args.warmup}s then measuring {args.duration}s "
          f"at concurrency {args.concurrency}...", file=sys.stderr)

    health_before = probe_health(args.endpoint, args.timeout)
    pacer = _Pacer(args.target_rps) if args.target_rps > 0 else None
    tallies = [Tally() for _ in range(args.concurrency)]
    start = time.monotonic()
    warmup_until = start + args.warmup
    stop_at = warmup_until + args.duration
    threads = [threading.Thread(target=_worker,
                                args=(args, key, stop_at, warmup_until, tallies[i], 1000 + i, pacer),
                                daemon=True)
               for i in range(args.concurrency)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    wall = time.monotonic() - warmup_until
    health_after = probe_health(args.endpoint, args.timeout)

    total = Tally()
    for t in tallies:
        total.merge(t)
    report = summarize(args, total, wall, health_before, health_after, key_source)
    print_report(report)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"  wrote {args.json_out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
