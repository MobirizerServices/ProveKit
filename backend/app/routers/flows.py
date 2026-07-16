"""Flows — CRUD for visual agent workflows + streamed run/step-debug."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Flow
from ..services import flow as engine

router = APIRouter(prefix="/api/flows", tags=["flows"])


def _f(f: Flow) -> dict:
    return {"id": f.id, "name": f.name, "description": f.description,
            "nodes": f.nodes, "edges": f.edges,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None}


@router.get("/node-types")
def node_types():
    return engine.NODE_TYPES


class FlowIn(BaseModel):
    name: str
    description: str = ""
    nodes: list = []
    edges: list = []


@router.get("")
def list_flows(db: Session = Depends(get_db)):
    return [{"id": f.id, "name": f.name, "description": f.description,
             "updated_at": f.updated_at.isoformat() if f.updated_at else None}
            for f in db.query(Flow).order_by(Flow.id).all()]


@router.post("")
def create_flow(payload: FlowIn, db: Session = Depends(get_db)):
    f = Flow(name=payload.name, description=payload.description, nodes=payload.nodes, edges=payload.edges)
    db.add(f); db.commit(); db.refresh(f)
    return _f(f)


@router.get("/{fid}")
def get_flow(fid: int, db: Session = Depends(get_db)):
    f = db.get(Flow, fid)
    if not f:
        raise HTTPException(404, "Flow not found")
    return _f(f)


@router.put("/{fid}")
def update_flow(fid: int, payload: FlowIn, db: Session = Depends(get_db)):
    f = db.get(Flow, fid)
    if not f:
        raise HTTPException(404, "Flow not found")
    f.name, f.description, f.nodes, f.edges = payload.name, payload.description, payload.nodes, payload.edges
    db.commit(); db.refresh(f)
    return _f(f)


@router.delete("/{fid}")
def delete_flow(fid: int, db: Session = Depends(get_db)):
    f = db.get(Flow, fid)
    if f:
        db.delete(f); db.commit()
    return {"deleted": True}


class RunPayload(BaseModel):
    input: dict = {}
    breakpoints: list[str] = []
    step: bool = False


@router.post("/{fid}/run/stream")
def run_stream(fid: int, payload: RunPayload, db: Session = Depends(get_db)):
    f = db.get(Flow, fid)
    if not f:
        raise HTTPException(404, "Flow not found")
    flow = {"nodes": f.nodes, "edges": f.edges}

    def events():
        for ev in engine.run_stream(db, flow, payload.input, breakpoints=set(payload.breakpoints), single_step=payload.step):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ContinuePayload(BaseModel):
    run_id: str
    node_id: str
    breakpoints: list[str] = []
    step: bool = False


@router.post("/{fid}/continue/stream")
def continue_stream(fid: int, payload: ContinuePayload, db: Session = Depends(get_db)):
    f = db.get(Flow, fid)
    if not f:
        raise HTTPException(404, "Flow not found")
    # pop (not peek) so two concurrent /continue calls can't resume the same run and corrupt its ctx.
    ctx = engine.pop_ctx(payload.run_id)
    if ctx is None:
        raise HTTPException(409, "Run context expired or already resumed — start a fresh run.")
    flow = {"nodes": f.nodes, "edges": f.edges}

    def events():
        for ev in engine.run_stream(db, flow, {}, breakpoints=set(payload.breakpoints), single_step=payload.step,
                                    start_at=payload.node_id, ctx=ctx, run_id=payload.run_id):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
