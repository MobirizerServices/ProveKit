"""Deployment helpers: API keys, slugs, and executing a frozen flow snapshot.

Deploying a flow snapshots its graph and mints an API key (shown once). Invoking a
deployment runs that snapshot through the same flow engine the canvas uses, so what you
tested is exactly what runs in production.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from . import flow as engine


def new_api_key() -> tuple[str, str]:
    """Return (plaintext, hash). Plaintext is shown to the user exactly once."""
    key = "agm_" + secrets.token_urlsafe(32)
    return key, hash_key(key)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def verify_key(key: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_key(key), key_hash)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "flow"


def run_snapshot(session, snapshot: dict, flow_input: dict, workspace_id: int, stream=False):
    """Execute a deployment's frozen flow. Yields the engine's events; the caller collects
    the terminal output (output-node values) or passes events through for streaming."""
    yield from engine.run_stream(session, {"nodes": snapshot.get("nodes", []),
                                           "edges": snapshot.get("edges", [])},
                                 flow_input or {}, workspace_id=workspace_id)


def collect_output(events: list[dict]) -> dict:
    """Reduce engine events to a deployment response: the output node values + status."""
    outputs, status, error, run_id = {}, "completed", "", None
    for ev in events:
        if ev.get("type") == "start":
            run_id = ev.get("run_id")
        elif ev.get("type") == "node" and ev.get("status") == "ok" and ev.get("node_type") == "output":
            val = (ev.get("output") or {}).get("value") if isinstance(ev.get("output"), dict) else ev.get("output")
            outputs[ev.get("title") or ev.get("node_id")] = val
        elif ev.get("type") == "node" and ev.get("status") == "error":
            status, error = "failed", ev.get("error", "")
        elif ev.get("type") in ("done", "error"):
            if ev.get("status"):
                status = ev["status"]
            if ev.get("type") == "error":
                status, error = "failed", ev.get("error", "")
    # A single output node returns its value directly; multiple return a name→value map.
    output = next(iter(outputs.values())) if len(outputs) == 1 else (outputs or None)
    return {"output": output, "status": status, "error": error, "run_id": run_id}
