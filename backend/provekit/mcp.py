"""ProveKit MCP server — debug your traces from any MCP client (Claude Desktop, Cursor, …).

This is a *debug channel*, not a second client SDK: your agent still installs only the one
`provekit` tracing SDK. This server runs wherever you like (your laptop, CI) and reads the
already-captured traces from your portal over HTTP, authenticated by the same project key.

    pip install "provekit[mcp]"
    export PROVEKIT_API_KEY=pk_...        # your project key
    export PROVEKIT_ENDPOINT=https://provekit.your-co.com
    provekit-mcp                          # speaks MCP over stdio

Then point an MCP client at the `provekit-mcp` command. It exposes tools to list recent
traces, surface failures, and pull a full span tree — so the assistant can reason over an
agent run and tell you what broke, with no code added to the traced app.
"""
from __future__ import annotations

import os

import httpx

_TIMEOUT = 15


def _base() -> tuple[str, dict]:
    """Resolve the portal URL + auth header from the environment, or raise a clear error."""
    key = os.environ.get("PROVEKIT_API_KEY")
    endpoint = os.environ.get("PROVEKIT_ENDPOINT")
    if not key or not endpoint:
        raise RuntimeError(
            "Set PROVEKIT_API_KEY (your pk_ project key) and PROVEKIT_ENDPOINT "
            "(your portal URL) before starting the ProveKit MCP server."
        )
    return endpoint.rstrip("/"), {"Authorization": f"Bearer {key}"}


def _get(path: str, **params):
    url, headers = _base()
    r = httpx.get(f"{url}/v1{path}", headers=headers, params=params, timeout=_TIMEOUT,
                  follow_redirects=False)
    r.raise_for_status()
    return r.json()


# ---- the callable data layer (import-safe; used by the MCP tools and by tests) ----
def list_traces(limit: int = 20, status: str | None = None) -> list[dict]:
    """Recent traces, newest first. Pass status='failed' to see only failed runs."""
    return _get("/traces", limit=limit, **({"status": status} if status else {}))


def list_failures(limit: int = 20) -> list[dict]:
    """Just the traces that ended in a failure — the ones worth debugging first."""
    return list_traces(limit=limit, status="failed")


def get_trace(trace_id: str) -> list[dict]:
    """Every span of one trace (the full nested flow), in start order."""
    return _get(f"/traces/{trace_id}")


def build_server():  # pragma: no cover - needs the optional `mcp` dep; glue over the tested data layer
    """Construct the FastMCP server with the trace tools registered. Imported lazily so the
    module stays importable (and testable) without the optional `mcp` dependency. The three
    data-layer functions above are registered directly as MCP tools."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("provekit")
    server.add_tool(list_traces, name="provekit_list_traces",
                    description="List recent ProveKit traces (agent runs). status='failed' filters to failures.")
    server.add_tool(list_failures, name="provekit_list_failures",
                    description="List recent traces that ended in a failure — start debugging here.")
    server.add_tool(get_trace, name="provekit_get_trace",
                    description="Fetch the full span tree of one trace by trace_id to inspect what happened.")
    return server


def main() -> None:  # pragma: no cover - blocks serving MCP over stdio; exercised by hand
    """Console-script entrypoint: `provekit-mcp`. Speaks MCP over stdio."""
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
