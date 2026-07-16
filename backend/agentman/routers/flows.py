"""Flows — CRUD for visual agent workflows + streamed run/step-debug."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import Connection, Flow, Workspace, iso_utc
from ..services import flow as engine
from ..services import testfile
from ..services.workspace import current_workspace
from .run import _active_vars


def _get(db, ws, fid) -> Flow:
    f = db.get(Flow, fid)
    if not f or f.workspace_id != ws.id:
        raise HTTPException(404, "Flow not found")
    return f

router = APIRouter(prefix="/api/flows", tags=["flows"])


def _f(f: Flow) -> dict:
    return {"id": f.id, "name": f.name, "description": f.description,
            "nodes": f.nodes, "edges": f.edges,
            "updated_at": iso_utc(f.updated_at)}


@router.get("/node-types")
def node_types():
    return engine.NODE_TYPES


class FlowIn(BaseModel):
    name: str
    description: str = ""
    nodes: list = []
    edges: list = []


@router.get("")
def list_flows(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    return [{"id": f.id, "name": f.name, "description": f.description,
             "updated_at": iso_utc(f.updated_at)}
            for f in db.query(Flow).filter(Flow.workspace_id == ws.id).order_by(Flow.id).all()]


def _check_nodes(nodes: list) -> None:
    from ..config import get_settings
    cap = get_settings().max_flow_nodes
    if cap and len(nodes or []) > cap:
        raise HTTPException(400, f"Flow too large: {len(nodes)} nodes (max {cap}).")


@router.post("")
def create_flow(payload: FlowIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    _check_nodes(payload.nodes)
    f = Flow(workspace_id=ws.id, name=payload.name, description=payload.description, nodes=payload.nodes, edges=payload.edges)
    db.add(f); db.commit(); db.refresh(f)
    return _f(f)


@router.get("/{fid}")
def get_flow(fid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    return _f(_get(db, ws, fid))


@router.get("/{fid}/export", response_class=PlainTextResponse)
def export_flow(fid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    f = _get(db, ws, fid)
    ids = {(n.get("config") or {}).get("connection_id") for n in (f.nodes or [])}
    ids.discard(None)
    names = {c.id: c.name for c in db.query(Connection).filter(Connection.workspace_id == ws.id, Connection.id.in_(ids)).all()} if ids else {}
    return testfile.dump_flow(f.name, f.description, f.nodes, f.edges, names)


@router.put("/{fid}")
def update_flow(fid: int, payload: FlowIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    _check_nodes(payload.nodes)
    f = _get(db, ws, fid)
    f.name, f.description, f.nodes, f.edges = payload.name, payload.description, payload.nodes, payload.edges
    db.commit(); db.refresh(f)
    return _f(f)


@router.delete("/{fid}")
def delete_flow(fid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    f = db.get(Flow, fid)
    if f and f.workspace_id == ws.id:
        db.delete(f); db.commit()
    return {"deleted": True}


class RunPayload(BaseModel):
    input: dict = {}
    breakpoints: list[str] = []
    step: bool = False


@router.post("/{fid}/run/stream")
def run_stream(fid: int, payload: RunPayload, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    f = _get(db, ws, fid)
    flow = {"nodes": f.nodes, "edges": f.edges}
    variables = _active_vars(db, ws.id)
    ws_id = ws.id

    def events():
        session = SessionLocal()  # request-scoped db is torn down before this generator runs
        try:
            for ev in engine.run_stream(session, flow, payload.input, breakpoints=set(payload.breakpoints),
                                        single_step=payload.step, variables=variables, workspace_id=ws_id):
                yield f"data: {json.dumps(ev)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            session.close()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ContinuePayload(BaseModel):
    run_id: str
    node_id: str
    breakpoints: list[str] = []
    step: bool = False


@router.post("/{fid}/continue/stream")
def continue_stream(fid: int, payload: ContinuePayload, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    f = _get(db, ws, fid)
    # pop (not peek) so two concurrent /continue calls can't resume the same run and corrupt its ctx.
    ctx = engine.pop_ctx(payload.run_id)
    if ctx is None:
        raise HTTPException(409, "Run context expired or already resumed — start a fresh run.")
    flow = {"nodes": f.nodes, "edges": f.edges}
    variables = _active_vars(db, ws.id)
    ws_id = ws.id

    def events():
        session = SessionLocal()
        try:
            for ev in engine.run_stream(session, flow, {}, breakpoints=set(payload.breakpoints), single_step=payload.step,
                                        start_at=payload.node_id, ctx=ctx, run_id=payload.run_id, variables=variables, workspace_id=ws_id):
                yield f"data: {json.dumps(ev)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            session.close()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
