#!/usr/bin/env python3
"""AgentMan load-test harness.

Fires N concurrent streaming runs against a running instance, reports latency
percentiles / throughput / error rate, and checks the server stays responsive.

    # against the keyless mock (no API key needed)
    python scripts/loadtest.py --n 100

    # against a real provider: create a connection first, pass its id and model
    python scripts/loadtest.py --n 50 --connection-id 2 --model gpt-4o-mini \
        --base http://localhost:8100

Exits non-zero if the error rate exceeds --max-error-rate or the server stops
responding to /healthz under load — so it can gate a release.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")


async def _one(client: httpx.AsyncClient, req: dict) -> tuple[bool, float, int]:
    t0 = time.monotonic()
    tokens = 0
    try:
        async with client.stream("POST", "/api/run/stream", json={"request": req, "save": False}) as r:
            if r.status_code != 200:
                return False, time.monotonic() - t0, 0
            async for line in r.aiter_lines():
                if line.startswith("data:") and '"delta"' in line:
                    tokens += 1
        return True, time.monotonic() - t0, tokens
    except Exception:
        return False, time.monotonic() - t0, 0


async def _resolve_mock(client: httpx.AsyncClient) -> tuple[int, str]:
    conns = (await client.get("/api/connections")).json()
    m = next((c for c in conns if c["config"].get("provider") == "mock"), None)
    if not m:
        sys.exit("no mock connection found; open the app once to seed it, or pass --connection-id")
    return m["id"], "demo-mock"


async def main(args) -> int:
    async with httpx.AsyncClient(base_url=args.base, timeout=args.timeout) as client:
        if args.connection_id:
            cid, model = args.connection_id, args.model
        else:
            cid, model = await _resolve_mock(client)
        req = {"type": "prompt", "connection_id": cid, "model": model, "user": args.prompt}

        print(f"→ {args.n} concurrent streams · connection {cid} · model {model}")
        t0 = time.monotonic()
        results = await asyncio.gather(*[_one(client, dict(req)) for _ in range(args.n)])
        wall = time.monotonic() - t0

        ok = [r for r in results if r[0]]
        lat = sorted(r[1] for r in ok)
        errors = len(results) - len(ok)
        err_rate = errors / len(results)

        def pct(p):
            return lat[min(len(lat) - 1, int(len(lat) * p))] if lat else 0.0

        # was the server still responsive under load?
        alive = (await client.get("/healthz")).status_code == 200

        print(f"\n  wall time      {wall:.2f}s")
        print(f"  throughput     {len(ok) / wall:.1f} completed streams/s")
        print(f"  latency p50    {pct(0.50):.2f}s")
        print(f"  latency p95    {pct(0.95):.2f}s")
        print(f"  latency max    {(lat[-1] if lat else 0):.2f}s")
        print(f"  errors         {errors}/{len(results)}  ({err_rate:.1%})")
        print(f"  server healthy after load: {alive}")

        failed = err_rate > args.max_error_rate or not alive
        print("\n" + ("✗ FAIL" if failed else "✓ PASS"))
        return 1 if failed else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AgentMan load test")
    p.add_argument("--base", default="http://localhost:8100")
    p.add_argument("--n", type=int, default=50, help="concurrent streams")
    p.add_argument("--connection-id", type=int, default=0, help="use a specific connection (else the mock)")
    p.add_argument("--model", default="demo-mock")
    p.add_argument("--prompt", default="Explain what an AI agent is in two sentences.")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--max-error-rate", type=float, default=0.02)
    sys.exit(asyncio.run(main(p.parse_args())))
