"""Collections, saved requests, environments (variables), and .agentman import/export.
Everything here is scoped to the caller's workspace."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Collection, Connection, Dataset, Environment, Flow, Request, Workspace
from ..services import testfile
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api", tags=["library"])


def _scoped(db, model, oid, ws):
    """Fetch a row by id only if it belongs to the workspace (else None)."""
    row = db.get(model, oid)
    return row if row and row.workspace_id == ws.id else None


# ---- collections ----
class CollectionIn(BaseModel):
    name: str


@router.get("/collections")
def list_collections(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    cols = db.query(Collection).filter(Collection.workspace_id == ws.id).order_by(Collection.id).all()
    reqs = db.query(Request).filter(Request.workspace_id == ws.id).order_by(Request.updated_at.desc()).all()
    by_col: dict[int | None, list] = {}
    for r in reqs:
        by_col.setdefault(r.collection_id, []).append(
            {"id": r.id, "name": r.name, "type": r.type, "collection_id": r.collection_id})
    return {
        "collections": [{"id": c.id, "name": c.name, "requests": by_col.get(c.id, [])} for c in cols],
        "loose": by_col.get(None, []),
    }


@router.post("/collections")
def create_collection(payload: CollectionIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    c = Collection(workspace_id=ws.id, name=payload.name)
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "name": c.name, "requests": []}


@router.delete("/collections/{cid}")
def delete_collection(cid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    c = _scoped(db, Collection, cid, ws)
    if c:
        for r in db.query(Request).filter(Request.collection_id == cid).all():
            r.collection_id = None
        db.delete(c); db.commit()
    return {"deleted": True}


# ---- requests ----
class RequestIn(BaseModel):
    name: str
    type: str
    payload: dict = {}
    collection_id: int | None = None


def _req(r: Request) -> dict:
    return {"id": r.id, "name": r.name, "type": r.type, "payload": r.payload,
            "collection_id": r.collection_id}


@router.post("/requests")
def save_request(payload: RequestIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = Request(workspace_id=ws.id, name=payload.name, type=payload.type, payload=payload.payload,
                collection_id=payload.collection_id)
    db.add(r); db.commit(); db.refresh(r)
    return _req(r)


@router.get("/requests/{rid}")
def get_request(rid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = _scoped(db, Request, rid, ws)
    if not r:
        raise HTTPException(404, "Request not found")
    return _req(r)


@router.put("/requests/{rid}")
def update_request(rid: int, payload: RequestIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = _scoped(db, Request, rid, ws)
    if not r:
        raise HTTPException(404, "Request not found")
    r.name, r.type, r.payload, r.collection_id = payload.name, payload.type, payload.payload, payload.collection_id
    db.commit(); db.refresh(r)
    return _req(r)


@router.delete("/requests/{rid}")
def delete_request(rid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = _scoped(db, Request, rid, ws)
    if r:
        db.delete(r); db.commit()
    return {"deleted": True}


# ---- .agentman file import/export (the git-diffable test format) ----
@router.get("/requests/{rid}/export", response_class=PlainTextResponse)
def export_request(rid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = _scoped(db, Request, rid, ws)
    if not r:
        raise HTTPException(404, "Request not found")
    payload = dict(r.payload or {})
    conn = _scoped(db, Connection, payload.get("connection_id"), ws) if payload.get("connection_id") else None
    return testfile.dump_test(r.name, payload, conn.name if conn else None)


class ImportIn(BaseModel):
    content: str
    collection_id: int | None = None


@router.post("/import")
def import_file(payload: ImportIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Import an .agentman document (test or flow). Connection names resolve within this
    workspace; an unresolved name imports fine but needs a connection re-pick."""
    try:
        doc = testfile.load(payload.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    def _resolve(name: str | None) -> int | None:
        if not name:
            return None
        c = db.query(Connection).filter(Connection.workspace_id == ws.id, Connection.name == name).first()
        return c.id if c else None

    if doc["kind"] == "test":
        req = dict(doc["request"])
        cid = _resolve(doc.get("connection"))
        if cid:
            req["connection_id"] = cid
        if doc.get("assertions"):
            req["assertions"] = doc["assertions"]
        r = Request(workspace_id=ws.id, name=doc.get("name") or "imported", type=req.get("type"),
                    payload=req, collection_id=payload.collection_id)
        db.add(r)
        d = None
        if doc.get("dataset"):
            d = Dataset(workspace_id=ws.id, name=doc.get("name") or "imported", rows=doc["dataset"])
            db.add(d)
        db.commit(); db.refresh(r)
        return {"kind": "test", "request": _req(r), "dataset_id": d.id if d else None,
                "connection_resolved": bool(cid) or not doc.get("connection")}

    nodes = []
    unresolved = 0
    for n in doc["nodes"]:
        cfg = dict(n.get("config") or {})
        cname = cfg.pop("connection", None)
        if cname:
            cfg["connection_id"] = _resolve(cname)
            unresolved += cfg["connection_id"] is None
        nodes.append({**n, "config": cfg})
    f = Flow(workspace_id=ws.id, name=doc.get("name") or "imported", description=doc.get("description") or "",
             nodes=nodes, edges=doc["edges"])
    db.add(f); db.commit(); db.refresh(f)
    return {"kind": "flow", "flow_id": f.id, "connection_resolved": unresolved == 0}


# ---- environments ----
class EnvironmentIn(BaseModel):
    name: str
    variables: dict = {}
    is_active: bool = False


@router.get("/environments")
def list_environments(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    return [{"id": e.id, "name": e.name, "variables": e.variables, "is_active": e.is_active}
            for e in db.query(Environment).filter(Environment.workspace_id == ws.id).order_by(Environment.id).all()]


@router.post("/environments")
def create_environment(payload: EnvironmentIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    e = Environment(workspace_id=ws.id, name=payload.name, variables=payload.variables, is_active=payload.is_active)
    db.add(e); db.commit(); db.refresh(e)
    return {"id": e.id, "name": e.name, "variables": e.variables, "is_active": e.is_active}


@router.put("/environments/{eid}")
def update_environment(eid: int, payload: EnvironmentIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    e = _scoped(db, Environment, eid, ws)
    if not e:
        raise HTTPException(404, "Environment not found")
    if payload.is_active:  # only one active at a time, within the workspace
        for other in db.query(Environment).filter(Environment.workspace_id == ws.id, Environment.id != eid).all():
            other.is_active = False
    e.name, e.variables, e.is_active = payload.name, payload.variables, payload.is_active
    db.commit()
    return {"id": e.id, "name": e.name, "variables": e.variables, "is_active": e.is_active}


@router.delete("/environments/{eid}")
def delete_environment(eid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    e = _scoped(db, Environment, eid, ws)
    if e:
        db.delete(e); db.commit()
    return {"deleted": True}


# ---- datasets (reusable input-row sets) ----
class DatasetIn(BaseModel):
    name: str
    rows: list = []


def _ds(d: Dataset) -> dict:
    return {"id": d.id, "name": d.name, "rows": d.rows}


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    return [_ds(d) for d in db.query(Dataset).filter(Dataset.workspace_id == ws.id).order_by(Dataset.id.desc()).all()]


@router.post("/datasets")
def create_dataset(payload: DatasetIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    d = Dataset(workspace_id=ws.id, name=payload.name, rows=payload.rows)
    db.add(d); db.commit(); db.refresh(d)
    return _ds(d)


@router.put("/datasets/{did}")
def update_dataset(did: int, payload: DatasetIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    d = _scoped(db, Dataset, did, ws)
    if not d:
        raise HTTPException(404, "Dataset not found")
    d.name, d.rows = payload.name, payload.rows
    db.commit()
    return _ds(d)


@router.delete("/datasets/{did}")
def delete_dataset(did: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    d = _scoped(db, Dataset, did, ws)
    if d:
        db.delete(d); db.commit()
    return {"deleted": True}
