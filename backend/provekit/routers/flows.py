"""Agent Flow Studio — visual workflows: author a node graph, publish a version, execute it.

The canvas stores one document per flow rather than normalised nodes/edges (see models.Flow),
so everything here reads and writes whole graphs.

Execution is a guarded walk, not a scheduler. From the trigger node it follows one outgoing
edge at a time, evaluating branch conditions to choose which. That is deliberately narrower
than a DAG runner: a flow the canvas can draw but the executor silently reorders would make
the visual run-history lie about what happened, and the run history is the point.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Flow, FlowRun, FlowVersion, ProviderConnection, Workspace, _now, iso_utc
from ..services import errors, flow_trace, limits, pricing
from ..services.llm_client import LLMError, complete
from ..services.sealing import unseal
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/flows", tags=["flows"])

#: Node types the canvas offers. `knowledge` is placeable but not executable — there is no
#: retriever wired up yet, and faking a vector search would put an invented document into a
#: trace that claims to be evidence.
NODE_TYPES = ("trigger", "agent", "model", "knowledge", "logic", "approval", "output")

#: Hard stop on a walk. A graph with a cycle is legal to draw (a retry loop) but must not run
#: forever; the run fails with the cap named rather than hanging the request.
MAX_STEPS = 25

#: Per-node completion ceiling — the same value the playground enforces, so a flow can't run
#: an unbounded (and unbounded-cost) completion the interactive path would have clamped.
_MAX_TOKENS_CAP = 4096


# ---------------------------------------------------------------- serialisation

def _flow_row(f: Flow, run_count: int = 0) -> dict:
    return {
        "id": f.id, "name": f.name, "description": f.description,
        "graph": f.graph or {"nodes": [], "edges": []},
        "version": f.version, "published_version": f.published_version,
        "run_count": run_count,
        "created_at": iso_utc(f.created_at), "updated_at": iso_utc(f.updated_at),
    }


def _run_row(r: FlowRun) -> dict:
    return {
        "id": r.id, "flow_id": r.flow_id, "version": r.version, "status": r.status,
        "input": r.input, "output": r.output, "error": r.error, "steps": r.steps or [],
        "duration_ms": r.duration_ms, "trace_id": r.trace_id,
        "created_at": iso_utc(r.created_at),
    }


def _version_row(v: FlowVersion) -> dict:
    return {"id": v.id, "flow_id": v.flow_id, "version": v.version, "graph": v.graph,
            "note": v.note, "created_at": iso_utc(v.created_at)}


def _own(db: Session, ws: Workspace, flow_id: int) -> Flow:
    f = db.get(Flow, flow_id)
    if not f or f.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("flow", "GET /api/flows"))
    return f


# ---------------------------------------------------------------- request bodies

class _FlowIn(BaseModel):
    name: str
    description: str = ""
    graph: dict = {}


class _FlowPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: dict | None = None


class _PublishIn(BaseModel):
    note: str = ""


class _RunIn(BaseModel):
    input: str = ""
    version: int | None = None       # default: the draft on the canvas
    connection_id: int | None = None
    provider: str | None = None      # "mock" runs without a stored key


# ---------------------------------------------------------------- graph validation

def _validate(graph: dict) -> tuple[list[dict], dict[str, list[dict]]]:
    """Return (nodes, edges-by-source). Raises 422 on a graph that cannot be walked."""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    if not nodes:
        raise HTTPException(422, "This flow has no nodes yet — add a trigger to start.")
    ids = {n.get("id") for n in nodes}
    for n in nodes:
        if n.get("type") not in NODE_TYPES:
            raise HTTPException(422, f"Unknown node type {n.get('type')!r}")
    for e in edges:
        if e.get("source") not in ids or e.get("target") not in ids:
            raise HTTPException(422, "An edge points at a node that isn't on the canvas.")
    by_source: dict[str, list[dict]] = {}
    for e in edges:
        by_source.setdefault(e["source"], []).append(e)
    return nodes, by_source


def _entry(nodes: list[dict], edges_by_source: dict[str, list[dict]]) -> dict:
    """The node a run starts from: an explicit trigger, else the only node nothing points at."""
    triggers = [n for n in nodes if n.get("type") == "trigger"]
    if len(triggers) == 1:
        return triggers[0]
    if len(triggers) > 1:
        raise HTTPException(422, "This flow has more than one trigger — a run wouldn't know where to start.")
    targeted = {e["target"] for es in edges_by_source.values() for e in es}
    roots = [n for n in nodes if n["id"] not in targeted]
    if len(roots) != 1:
        raise HTTPException(422, "Add a trigger node so the run has a single starting point.")
    return roots[0]


# ---------------------------------------------------------------- branch conditions

def _matches(cond: dict, text: str) -> bool:
    op = (cond.get("op") or "contains").lower()
    value = str(cond.get("value") or "")
    hay = text or ""
    if op == "contains":
        return value.lower() in hay.lower()
    if op == "equals":
        return hay.strip().lower() == value.strip().lower()
    if op == "not_contains":
        return value.lower() not in hay.lower()
    if op in ("gt", "lt"):
        try:
            return float(hay.strip()) > float(value) if op == "gt" else float(hay.strip()) < float(value)
        except ValueError:
            return False
    return False


def _pick_edge(node: dict, out: list[dict], text: str) -> dict | None:
    """Choose the outgoing edge. Only `logic` nodes branch; everything else has one exit."""
    if not out:
        return None
    if node.get("type") != "logic":
        return out[0]
    for cond in (node.get("config") or {}).get("conditions") or []:
        if _matches(cond, text):
            label = cond.get("label") or ""
            match = next((e for e in out if (e.get("label") or "") == label), None)
            if match:
                return match
    # No condition matched — fall through the edge explicitly marked else, if there is one.
    return next((e for e in out if (e.get("label") or "").lower() == "else"), None) or out[0]


# ---------------------------------------------------------------- the executor

async def _run_node(node: dict, text: str, db: Session, ws: Workspace,
                    data: _RunIn) -> tuple[str, str]:
    """Execute one node. Returns (output_text, note). Raises LLMError on a provider failure."""
    kind = node.get("type")
    cfg = node.get("config") or {}

    if kind in ("trigger", "output"):
        return text, ""

    if kind == "approval":
        # A test run cannot block on a human, so it proceeds and says so. Recording it as a
        # silent pass would make the run history claim an approval happened.
        return text, "auto-approved (test run — no reviewer was asked)"

    if kind == "knowledge":
        return text, "skipped — no retriever is configured for this workspace"

    if kind == "logic":
        return text, ""

    if kind in ("agent", "model"):
        model = cfg.get("model") or "gpt-4o-mini"
        provider, api_key, base_url = _resolve_provider(db, ws, data)
        system = cfg.get("system") or ""
        template = cfg.get("prompt") or "{{input}}"
        prompt = template.replace("{{input}}", text or "")
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        params = dict(cfg.get("params") or {})
        # Same ceiling the playground enforces: a node config can't ask for an unbounded
        # completion and run up the bill. A flow can chain up to MAX_STEPS of these.
        if params.get("max_tokens"):
            params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
        result = await complete(provider, model, messages, params,
                                api_key=api_key, base_url=base_url)
        # Accrue the call's cost toward the monthly cap. Each node is a real billable call, so
        # a flow that skipped this would let the executor spend past a cap the playground and
        # replay both respect — the check at run start would never see what the run spent.
        usage = result.get("usage") or {}
        limits.record_spend(ws.id, pricing.estimate(model, usage.get("input_tokens"),
                                                    usage.get("output_tokens")))
        return result.get("output", ""), f"{provider} · {model}"

    return text, ""


def _resolve_provider(db: Session, ws: Workspace, data: _RunIn) -> tuple[str, str, str]:
    if data.connection_id is not None:
        c = db.get(ProviderConnection, data.connection_id)
        if not c or c.workspace_id != ws.id:
            raise HTTPException(404, errors.not_in_project("model connection", "GET /api/connections"))
        c.last_used_at = _now(); db.commit()
        return c.provider, (unseal(c.key_sealed) if c.key_sealed else ""), c.base_url
    if (data.provider or "").lower() == "mock":
        return "mock", "", ""
    raise HTTPException(422, errors.NO_MODEL_CHOSEN)


# ---------------------------------------------------------------- routes

@router.get("")
def list_flows(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(Flow).filter(Flow.workspace_id == ws.id)
            .order_by(Flow.updated_at.desc()).all())
    counts = {}
    for f in rows:
        counts[f.id] = (db.query(FlowRun)
                        .filter(FlowRun.workspace_id == ws.id, FlowRun.flow_id == f.id).count())
    return [_flow_row(f, counts.get(f.id, 0)) for f in rows]


@router.post("")
def create_flow(data: _FlowIn, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    if not data.name.strip():
        raise HTTPException(422, "A flow needs a name.")
    f = Flow(workspace_id=ws.id, name=data.name.strip()[:160], description=data.description,
             graph=data.graph or {"nodes": [], "edges": []})
    db.add(f); db.commit(); db.refresh(f)
    return _flow_row(f)


@router.get("/{flow_id}")
def get_flow(flow_id: int, db: Session = Depends(get_db),
             ws: Workspace = Depends(current_workspace)):
    return _flow_row(_own(db, ws, flow_id))


@router.patch("/{flow_id}")
def update_flow(flow_id: int, data: _FlowPatch, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    f = _own(db, ws, flow_id)
    if data.name is not None:
        f.name = data.name.strip()[:160]
    if data.description is not None:
        f.description = data.description
    if data.graph is not None:
        f.graph = data.graph
        f.version += 1          # the draft moves; published_version stays where it was
    db.commit(); db.refresh(f)
    return _flow_row(f)


@router.delete("/{flow_id}")
def delete_flow(flow_id: int, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    f = _own(db, ws, flow_id)
    db.query(FlowVersion).filter(FlowVersion.flow_id == f.id,
                                 FlowVersion.workspace_id == ws.id).delete()
    db.query(FlowRun).filter(FlowRun.flow_id == f.id,
                             FlowRun.workspace_id == ws.id).delete()
    db.delete(f); db.commit()
    return {"ok": True}


@router.post("/{flow_id}/publish")
def publish_flow(flow_id: int, data: _PublishIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    """Freeze the current draft as an immutable version and mark it live."""
    f = _own(db, ws, flow_id)
    _validate(f.graph or {})     # refuse to publish a graph that could not run
    snap = FlowVersion(workspace_id=ws.id, flow_id=f.id, version=f.version,
                       graph=f.graph, note=data.note[:300])
    f.published_version = f.version
    db.add(snap); db.commit(); db.refresh(snap)
    return {"flow": _flow_row(f), "version": _version_row(snap)}


@router.get("/{flow_id}/versions")
def list_versions(flow_id: int, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    _own(db, ws, flow_id)
    rows = (db.query(FlowVersion)
            .filter(FlowVersion.workspace_id == ws.id, FlowVersion.flow_id == flow_id)
            .order_by(FlowVersion.version.desc()).all())
    return [_version_row(v) for v in rows]


@router.post("/{flow_id}/restore/{version}")
def restore_version(flow_id: int, version: int, db: Session = Depends(get_db),
                    ws: Workspace = Depends(current_workspace)):
    """Copy a frozen snapshot back onto the draft. The snapshot itself is never mutated."""
    f = _own(db, ws, flow_id)
    v = (db.query(FlowVersion)
         .filter(FlowVersion.workspace_id == ws.id, FlowVersion.flow_id == flow_id,
                 FlowVersion.version == version).first())
    if not v:
        raise HTTPException(404, "No such version")
    f.graph = v.graph
    f.version += 1
    db.commit(); db.refresh(f)
    return _flow_row(f)


@router.get("/{flow_id}/runs")
def list_runs(flow_id: int, limit: int = 20, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    _own(db, ws, flow_id)
    rows = (db.query(FlowRun)
            .filter(FlowRun.workspace_id == ws.id, FlowRun.flow_id == flow_id)
            .order_by(FlowRun.id.desc()).limit(min(limit, 100)).all())
    return [_run_row(r) for r in rows]


@router.post("/{flow_id}/run")
async def run_flow(flow_id: int, data: _RunIn, db: Session = Depends(get_db),
                   ws: Workspace = Depends(current_workspace)):
    """Execute the flow once and record every step, so the canvas can replay the run."""
    limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    f = _own(db, ws, flow_id)

    graph = f.graph or {}
    if data.version is not None:
        v = (db.query(FlowVersion)
             .filter(FlowVersion.workspace_id == ws.id, FlowVersion.flow_id == flow_id,
                     FlowVersion.version == data.version).first())
        if not v:
            raise HTTPException(404, "No such version")
        graph = v.graph or {}

    nodes, by_source = _validate(graph)
    node_by_id = {n["id"]: n for n in nodes}
    current = _entry(nodes, by_source)

    run = FlowRun(workspace_id=ws.id, flow_id=f.id,
                  version=data.version or f.version, status="running", input=data.input)
    db.add(run); db.commit(); db.refresh(run)

    text = data.input
    steps: list[dict] = []
    started = time.monotonic()
    status, error = "completed", ""

    for _ in range(MAX_STEPS):
        t0 = time.monotonic()
        try:
            text, note = await _run_node(current, text, db, ws, data)
            step_status = "skipped" if current.get("type") == "knowledge" else "ok"
        except LLMError as exc:
            steps.append({"node_id": current["id"], "label": current.get("label", ""),
                          "type": current.get("type"), "status": "failed",
                          "duration_ms": round((time.monotonic() - t0) * 1000),
                          "output": "", "note": "", "error": str(exc)})
            status, error = "failed", str(exc)
            break
        steps.append({"node_id": current["id"], "label": current.get("label", ""),
                      "type": current.get("type"), "status": step_status,
                      "duration_ms": round((time.monotonic() - t0) * 1000),
                      "output": (text or "")[:2000], "note": note, "error": ""})

        nxt = _pick_edge(current, by_source.get(current["id"], []), text)
        if nxt is None:
            break
        current = node_by_id[nxt["target"]]
    else:
        status = "failed"
        error = f"Stopped after {MAX_STEPS} steps — this flow probably has a loop."

    run.status = status
    run.error = error
    run.output = (text or "")[:8000]
    run.steps = steps
    run.duration_ms = round((time.monotonic() - started) * 1000)
    db.commit(); db.refresh(run)

    # Land the execution in the trace store too, so a flow run is visible to search, the
    # waterfall, datasets and sharing rather than only to this canvas. Best-effort: the run
    # itself already succeeded, and failing to write its trace must not change that verdict.
    run.trace_id = flow_trace.record(
        db, ws, flow_name=f.name, version=run.version, run_input=run.input,
        run_output=run.output, error=run.error, steps=steps, duration_ms=run.duration_ms)
    if run.trace_id:
        db.commit(); db.refresh(run)
    return _run_row(run)
