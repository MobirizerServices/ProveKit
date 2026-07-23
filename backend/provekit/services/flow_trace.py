"""Write a flow execution into the trace store as ordinary spans.

A flow run that only existed in `flow_runs` was a second, private history: the canvas could
replay it but nothing else could. Search, the waterfall, datasets, sharing, retention and
evaluation all read `runs`, so a flow execution that isn't there is invisible to every tool
the product otherwise points you at.

So a run becomes one root span for the flow and one child per executed node, written through
the same path an SDK-captured trace takes — redaction first, then `search_text` built from the
already-redacted row, exactly as `routers/traces._persist_spans` does. Diverging here would
produce spans that leak what ingest masks, or that search can't find.
"""
from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Run, Workspace
from . import redact
from . import search as search_svc

#: Flow node type -> span type. The trace store only knows agent/llm/tool/step, and the portal
#: colours and filters on those, so a node has to land as one of them rather than as its own
#: kind that every existing view would then have to learn.
_SPAN_TYPE = {
    "trigger": "step",
    "agent": "llm",
    "model": "llm",
    "knowledge": "tool",
    "logic": "step",
    "approval": "step",
    "output": "step",
}


def spans_for(flow_name: str, version: int, run_input: str, run_output: str,
              error: str, steps: list[dict], duration_ms: int) -> tuple[str, list[dict]]:
    """Build (trace_id, span rows) for one flow execution. Pure — no session, no IO."""
    trace_id = secrets.token_hex(16)
    root_span = secrets.token_hex(8)

    failed = bool(error) or any(s.get("status") == "failed" for s in steps)
    rows: list[dict] = [dict(
        type="agent",
        label=f"flow · {flow_name}",
        request={"type": "flow", "operation": "invoke_flow", "input": run_input,
                 "model": "", "provider": "provekit.flows"},
        result={"text": run_output, "meta": {"flow": flow_name, "flow_version": version,
                                             "node_count": len(steps)}},
        status="failed" if failed else "completed",
        duration_ms=duration_ms,
        error=error,
        trace_id=trace_id, span_id=root_span, parent_span_id="",
    )]

    for i, s in enumerate(steps):
        node_type = s.get("type") or "step"
        meta = {"flow": flow_name, "flow_version": version,
                "node_id": s.get("node_id", ""), "node_type": node_type, "step": i}
        if s.get("note"):
            # The executor's note is the only record of *why* a node was skipped or
            # auto-approved; dropping it here would make the trace overstate what ran.
            meta["note"] = s["note"]
        rows.append(dict(
            type=_SPAN_TYPE.get(node_type, "step"),
            label=s.get("label") or node_type,
            request={"type": node_type, "operation": node_type, "input": "",
                     "model": "", "provider": "provekit.flows"},
            result={"text": s.get("output", ""), "meta": meta},
            status={"ok": "completed", "failed": "failed"}.get(s.get("status", ""), "completed"),
            duration_ms=int(s.get("duration_ms") or 0),
            error=s.get("error") or "",
            trace_id=trace_id, span_id=secrets.token_hex(8), parent_span_id=root_span,
        ))
    return trace_id, rows


def record(db: Session, ws: Workspace, flow_name: str, version: int, run_input: str,
           run_output: str, error: str, steps: list[dict], duration_ms: int) -> str:
    """Persist a flow execution as a trace and return its trace_id.

    Never raises: a flow run that succeeded must not be reported as failed because writing its
    trace didn't. The caller leaves `trace_id` empty in that case.
    """
    try:
        trace_id, rows = spans_for(flow_name, version, run_input, run_output,
                                   error, steps, duration_ms)
        if ws.redact_pii or get_settings().redact_pii:
            rows = [redact.scrub_run(kw) for kw in rows]
        for kw in rows:
            db.add(Run(workspace_id=ws.id, search_text=search_svc.text_for(kw), **kw))
        db.commit()
        return trace_id
    except Exception:                                    # noqa: BLE001 - see docstring
        db.rollback()
        return ""
