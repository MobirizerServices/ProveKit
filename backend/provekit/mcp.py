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

It also exposes a small set of *write* tools, so the loop the channel exists for can finish:
find a failing trace → put it in the regression dataset → run the eval. Writes from an agent
get stricter rules than reads:

- **Nothing destructive.** There is no delete or edit tool. Every write appends. The worst an
  assistant can do is add a row you can remove in the portal; it can never remove one you
  curated, and it can never rewrite the `expected` a past experiment was scored against.
- **Say it before doing it.** `provekit_preview_dataset_item` renders the exact {input,
  expected} a promotion would write, against the named dataset, and writes nothing.
- **Name the target back.** Every write resolves the dataset id first and echoes the dataset
  *name* in its result, so "wrote to dataset 7" is checkable rather than hopeful.
- **Refuse the ambiguous case.** Promoting a span twice, creating a second dataset with an
  existing name, or evaluating an empty dataset all raise with the id you probably meant,
  and write nothing.
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


def _post(path: str, payload: dict) -> dict:
    """POST to the key-authed API, turning a failure into a sentence rather than a status code.

    A write tool that fails with a bare `HTTPStatusError` invites the assistant to retry, and a
    retried write is how you get two copies of the same dataset item. Surfacing the portal's own
    `detail` lets the model tell "dataset 7 doesn't exist" apart from "try again".
    """
    url, headers = _base()
    r = httpx.post(f"{url}/v1{path}", headers=headers, json=payload, timeout=_TIMEOUT,
                   follow_redirects=False)
    if r.status_code >= 400:
        try:
            detail = str(r.json().get("detail", ""))
        except Exception:
            detail = r.text[:200]
        hint = ""
        if r.status_code in (404, 405) and detail in ("", "Not Found", "Method Not Allowed"):
            # No such *route* — an older portal serving only the read half of /v1. Distinct
            # from a 404 that means the dataset itself is gone, which arrives with a detail.
            hint = (" This portal does not serve key-authed writes at that path; upgrade it "
                    "to a build that includes them.")
        raise RuntimeError(f"POST /v1{path} failed: HTTP {r.status_code} {detail}{hint}".strip())
    return r.json()


# ---- reads (import-safe; used by the MCP tools and by tests) ----
def list_traces(limit: int = 20, status: str | None = None) -> list[dict]:
    """Recent traces, newest first. Pass status='failed' to see only failed runs."""
    return _get("/traces", limit=limit, **({"status": status} if status else {}))


def list_failures(limit: int = 20) -> list[dict]:
    """Just the traces that ended in a failure — the ones worth debugging first."""
    return list_traces(limit=limit, status="failed")


def get_trace(trace_id: str) -> list[dict]:
    """Every span of one trace (the full nested flow), in start order."""
    return _get(f"/traces/{trace_id}")


def list_datasets() -> list[dict]:
    """Every dataset in this project with its id, name and item count."""
    return _get("/datasets")


# ---- promotion: turning a captured span into a dataset item ----
def _span_menu(spans: list[dict], limit: int = 20) -> str:
    return ", ".join(f"{s.get('span_id')} ({s.get('type')}: {s.get('label')})" for s in spans[:limit])


def _pick_span(spans: list[dict], span_id: str | None) -> dict:
    """The span a dataset item should be built from: the one asked for, else the trace root.

    With no span_id the root is the right default — it holds the run as the caller saw it,
    question in and final answer out. There is deliberately no "first span" fallback when a
    trace has no root: that quietly promotes whichever fragment happened to arrive first, and
    an item holding a tool's arguments instead of the user's question looks fine in the list
    and poisons every experiment that runs against it.
    """
    if span_id:
        for s in spans:
            if s.get("span_id") == span_id:
                return s
        raise ValueError(f"span_id {span_id!r} is not in trace. Spans in it: {_span_menu(spans)}")
    roots = [s for s in spans if not s.get("parent_span_id")]
    if not roots:
        raise ValueError(
            "This trace has no root span (it arrived partial), so there is no obvious input/output "
            f"pair to promote. Pass span_id explicitly. Spans in it: {_span_menu(spans)}")
    return roots[0]


def _io(span: dict) -> tuple[str, str]:
    """(input, recorded output) of a span, read exactly the way the portal's own from-trace
    seeding reads it — so an item promoted over MCP is byte-identical to one promoted from the
    UI, and the two doors can't drift into disagreeing about what a trace contained."""
    req, res = span.get("request"), span.get("result")
    inp = req.get("input", "") if isinstance(req, dict) else ""
    out = res.get("text") or "" if isinstance(res, dict) else ""
    return inp or "", out or ""


def _dataset(dataset_id: int) -> dict:
    """Resolve a dataset id to its row, or refuse. Every write goes through this: confirming
    the id exists *and* handing the name back is what makes "wrote to dataset 7" auditable
    instead of a guess the assistant made from a stale listing."""
    for d in list_datasets():
        if d["id"] == dataset_id:
            return d
    raise ValueError(f"No dataset with id {dataset_id} in this project. Nothing was written — call "
                     "provekit_list_datasets for the ids you can write to.")


def _same_source(meta: dict, trace_id: str, span_id: str, is_root: bool) -> bool:
    """Was this item already promoted from this span? Items seeded from the portal predate
    span-level promotion and carry only a trace_id; they always came from the root, so that's
    what they're compared against."""
    if (meta or {}).get("trace_id") != trace_id:
        return False
    stored = (meta or {}).get("span_id")
    return stored == span_id if stored else is_root


def _existing_item(dataset_id: int, trace_id: str, span_id: str, is_root: bool) -> dict | None:
    for it in _get(f"/datasets/{dataset_id}/items"):
        if _same_source(it.get("meta") or {}, trace_id, span_id, is_root):
            return it
    return None


def preview_dataset_item(trace_id: str, span_id: str | None = None,
                         dataset_id: int | None = None) -> dict:
    """The {input, expected} that promoting this trace would write. Writes nothing."""
    spans = get_trace(trace_id)
    span = _pick_span(spans, span_id)
    sid = span.get("span_id") or ""
    inp, out = _io(span)
    warnings = []
    if not inp:
        warnings.append("This span recorded no input, so there would be nothing to run the item "
                        "against — provekit_add_trace_to_dataset will refuse it. Pick a span that "
                        "carries the request.")
    if not out:
        warnings.append("This span recorded no output, so `expected` would be empty unless you pass "
                        "one. A failing run is usually exactly this case: supply the answer it "
                        "should have given.")
    preview = {"writes": "nothing — this is a preview",
               "trace_id": trace_id, "span_id": sid, "span_label": span.get("label"),
               "span_type": span.get("type"), "span_status": span.get("status"),
               "input": inp, "expected": out,
               "expected_source": "the span's recorded output" if out else "empty",
               "warnings": warnings}
    if dataset_id is not None:
        d = _dataset(dataset_id)
        dup = _existing_item(dataset_id, trace_id, sid, not span.get("parent_span_id"))
        preview["target"] = {"dataset_id": d["id"], "dataset_name": d["name"],
                             "item_count_now": d["item_count"],
                             "already_holds_this_span": bool(dup),
                             "existing_item_id": dup["id"] if dup else None}
    return preview


def add_trace_to_dataset(dataset_id: int, trace_id: str, span_id: str | None = None,
                         expected: str | None = None, allow_duplicate: bool = False) -> dict:
    """Append one {input, expected} item to a dataset, built from a captured span. Appends only."""
    spans = get_trace(trace_id)
    span = _pick_span(spans, span_id)
    sid = span.get("span_id") or ""
    inp, out = _io(span)
    if not inp:
        raise ValueError(f"Span {sid} recorded no input, so the item would have nothing to run "
                         "against. Nothing was written — use provekit_preview_dataset_item to find "
                         "a span that carries the request.")
    d = _dataset(dataset_id)
    if not allow_duplicate:
        dup = _existing_item(dataset_id, trace_id, sid, not span.get("parent_span_id"))
        if dup:
            raise ValueError(
                f"Dataset {d['id']} ({d['name']!r}) already holds this span as item {dup['id']}. "
                "Nothing was written. Pass allow_duplicate=True only if a second copy is intended.")
    item = _post(f"/datasets/{dataset_id}/items",
                 {"input": inp, "expected": out if expected is None else expected,
                  "meta": {"trace_id": trace_id, "span_id": sid, "source": "mcp"}})
    return {"changed": f"Added 1 item to dataset {d['id']} ({d['name']!r}).",
            "dataset_id": d["id"], "dataset_name": d["name"],
            "item_count_now": d["item_count"] + 1, "item": item}


def create_dataset(name: str, description: str = "") -> dict:
    """Create a new, empty dataset. Refuses if the name is already taken."""
    name = (name or "").strip()
    if not name:
        raise ValueError("A dataset needs a name. Nothing was created.")
    for d in list_datasets():
        if d["name"].strip().lower() == name.lower():
            # Two datasets called "regression" is worse than no new dataset: every later write
            # is a coin flip between them, and nothing in the portal shows which one CI reads.
            raise ValueError(
                f"A dataset named {d['name']!r} already exists (id={d['id']}, {d['item_count']} "
                f"items). Nothing was created — add to it with dataset_id={d['id']}, or pick a "
                "different name.")
    d = _post("/datasets", {"name": name, "description": description})
    return {"changed": f"Created empty dataset {d['id']} ({d['name']!r}).", **d}


def start_experiment(dataset_id: int, name: str) -> dict:
    """Register an experiment (an evaluation run) over a dataset and return its id."""
    d = _dataset(dataset_id)
    if not d["item_count"]:
        raise ValueError(f"Dataset {d['id']} ({d['name']!r}) has no items, so an experiment over it "
                         "would score nothing. Nothing was created — add items first.")
    e = _post("/experiments", {"name": name, "dataset_id": dataset_id})
    return {"changed": f"Registered experiment {e['id']} ({e['name']!r}) over dataset {d['id']} "
                       f"({d['name']!r}), {d['item_count']} items, 0 results so far.",
            "experiment_id": e["id"], "name": e["name"],
            "dataset_id": d["id"], "dataset_name": d["name"], "item_count": d["item_count"],
            "result_count": 0,
            "scored": False,
            "how_results_arrive": (
                "ProveKit never calls your agent, so this experiment is an empty container until "
                "something that can run your target posts into it: "
                f"pk.evaluate({d['name']!r}, target, scorers=[...]) from your code or CI, or "
                f"POST /v1/experiments/{e['id']}/results. Note pk.evaluate registers its own "
                "experiment, so use this tool when the run needs an id up front — otherwise just "
                "run pk.evaluate and skip it.")}


def build_server():  # pragma: no cover - needs the optional `mcp` dep; glue over the tested data layer
    """Construct the FastMCP server with the trace tools registered. Imported lazily so the
    module stays importable (and testable) without the optional `mcp` dependency. The
    data-layer functions above are registered directly as MCP tools.

    Descriptions are long on purpose. A tool an assistant calls to *write* is chosen from its
    description alone, and "adds a trace to a dataset" is exactly vague enough to get called
    with the wrong dataset id; each one below says what it changes, what it will not do, and
    which tool to reach for instead."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("provekit")
    server.add_tool(list_traces, name="provekit_list_traces",
                    description="READ-ONLY. List recent ProveKit traces (agent runs). status='failed' filters to failures.")
    server.add_tool(list_failures, name="provekit_list_failures",
                    description="READ-ONLY. List recent traces that ended in a failure — start debugging here.")
    server.add_tool(get_trace, name="provekit_get_trace",
                    description="READ-ONLY. Fetch the full span tree of one trace by trace_id to inspect what happened.")
    server.add_tool(list_datasets, name="provekit_list_datasets",
                    description=("READ-ONLY. List this project's evaluation datasets with their id, name and item "
                                 "count. Call this before any write: dataset_id is the only way to target a "
                                 "dataset, and picking one from a remembered name is how a write lands in the "
                                 "wrong set."))
    server.add_tool(preview_dataset_item, name="provekit_preview_dataset_item",
                    description=("READ-ONLY dry run of provekit_add_trace_to_dataset. Shows the exact {input, "
                                 "expected} that would be written from a trace (root span by default, or the span "
                                 "you name), plus warnings when the span carries no input or no output. Pass "
                                 "dataset_id to also see which dataset it would land in, its current size, and "
                                 "whether that span is already in it. Writes nothing. Use this first whenever the "
                                 "user has not named an exact span."))
    server.add_tool(add_trace_to_dataset, name="provekit_add_trace_to_dataset",
                    description=("WRITES: appends ONE {input, expected} item to an existing dataset, built from a "
                                 "captured trace — the root span by default, or span_id for one step of it. The "
                                 "span's recorded output becomes `expected` unless you pass expected= (do that for "
                                 "a failing run: the recorded output is the wrong answer). Requires a numeric "
                                 "dataset_id from provekit_list_datasets; it never resolves names. Refuses, "
                                 "writing nothing, if the span has no input or if that span is already in the "
                                 "dataset (allow_duplicate=True overrides). Only ever adds — it cannot edit or "
                                 "remove an existing item."))
    server.add_tool(create_dataset, name="provekit_create_dataset",
                    description=("WRITES: creates a new EMPTY dataset and returns its id. Use only when no suitable "
                                 "dataset exists — check provekit_list_datasets first. Refuses if the name is "
                                 "already taken, and tells you the existing id to add to instead. Adds no items; "
                                 "follow with provekit_add_trace_to_dataset."))
    server.add_tool(start_experiment, name="provekit_start_experiment",
                    description=("WRITES: registers an experiment (one evaluation run) over a dataset and returns "
                                 "its id. It does NOT execute anything — ProveKit cannot call your agent, so the "
                                 "experiment holds zero results until your code or CI posts them (pk.evaluate). "
                                 "Never report an experiment as passed or failed on the strength of this call. "
                                 "Refuses on an empty dataset."))
    return server


def main() -> None:  # pragma: no cover - blocks serving MCP over stdio; exercised by hand
    """Console-script entrypoint: `provekit-mcp`. Speaks MCP over stdio."""
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
