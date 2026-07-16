"""Collections, saved requests, and environments (variables)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Collection, Dataset, Environment, Request

router = APIRouter(prefix="/api", tags=["library"])


# ---- collections ----
class CollectionIn(BaseModel):
    name: str


@router.get("/collections")
def list_collections(db: Session = Depends(get_db)):
    cols = db.query(Collection).order_by(Collection.id).all()
    reqs = db.query(Request).order_by(Request.updated_at.desc()).all()
    by_col: dict[int | None, list] = {}
    for r in reqs:
        by_col.setdefault(r.collection_id, []).append(
            {"id": r.id, "name": r.name, "type": r.type, "collection_id": r.collection_id})
    return {
        "collections": [{"id": c.id, "name": c.name,
                         "requests": by_col.get(c.id, [])} for c in cols],
        "loose": by_col.get(None, []),
    }


@router.post("/collections")
def create_collection(payload: CollectionIn, db: Session = Depends(get_db)):
    c = Collection(name=payload.name)
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "name": c.name, "requests": []}


@router.delete("/collections/{cid}")
def delete_collection(cid: int, db: Session = Depends(get_db)):
    c = db.get(Collection, cid)
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


@router.post("/requests")
def save_request(payload: RequestIn, db: Session = Depends(get_db)):
    r = Request(name=payload.name, type=payload.type, payload=payload.payload,
                collection_id=payload.collection_id)
    db.add(r); db.commit(); db.refresh(r)
    return _req(r)


@router.get("/requests/{rid}")
def get_request(rid: int, db: Session = Depends(get_db)):
    r = db.get(Request, rid)
    if not r:
        raise HTTPException(404, "Request not found")
    return _req(r)


@router.put("/requests/{rid}")
def update_request(rid: int, payload: RequestIn, db: Session = Depends(get_db)):
    r = db.get(Request, rid)
    if not r:
        raise HTTPException(404, "Request not found")
    r.name, r.type, r.payload, r.collection_id = payload.name, payload.type, payload.payload, payload.collection_id
    db.commit(); db.refresh(r)
    return _req(r)


@router.delete("/requests/{rid}")
def delete_request(rid: int, db: Session = Depends(get_db)):
    r = db.get(Request, rid)
    if r:
        db.delete(r); db.commit()
    return {"deleted": True}


def _req(r: Request) -> dict:
    return {"id": r.id, "name": r.name, "type": r.type, "payload": r.payload,
            "collection_id": r.collection_id}


# ---- environments ----
class EnvironmentIn(BaseModel):
    name: str
    variables: dict = {}
    is_active: bool = False


@router.get("/environments")
def list_environments(db: Session = Depends(get_db)):
    return [{"id": e.id, "name": e.name, "variables": e.variables, "is_active": e.is_active}
            for e in db.query(Environment).order_by(Environment.id).all()]


@router.post("/environments")
def create_environment(payload: EnvironmentIn, db: Session = Depends(get_db)):
    e = Environment(name=payload.name, variables=payload.variables, is_active=payload.is_active)
    db.add(e); db.commit(); db.refresh(e)
    return {"id": e.id, "name": e.name, "variables": e.variables, "is_active": e.is_active}


@router.put("/environments/{eid}")
def update_environment(eid: int, payload: EnvironmentIn, db: Session = Depends(get_db)):
    e = db.get(Environment, eid)
    if not e:
        raise HTTPException(404, "Environment not found")
    if payload.is_active:  # only one active at a time
        for other in db.query(Environment).filter(Environment.id != eid).all():
            other.is_active = False
    e.name, e.variables, e.is_active = payload.name, payload.variables, payload.is_active
    db.commit()
    return {"id": e.id, "name": e.name, "variables": e.variables, "is_active": e.is_active}


@router.delete("/environments/{eid}")
def delete_environment(eid: int, db: Session = Depends(get_db)):
    e = db.get(Environment, eid)
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
def list_datasets(db: Session = Depends(get_db)):
    return [_ds(d) for d in db.query(Dataset).order_by(Dataset.id.desc()).all()]


@router.post("/datasets")
def create_dataset(payload: DatasetIn, db: Session = Depends(get_db)):
    d = Dataset(name=payload.name, rows=payload.rows)
    db.add(d); db.commit(); db.refresh(d)
    return _ds(d)


@router.put("/datasets/{did}")
def update_dataset(did: int, payload: DatasetIn, db: Session = Depends(get_db)):
    d = db.get(Dataset, did)
    if not d:
        raise HTTPException(404, "Dataset not found")
    d.name, d.rows = payload.name, payload.rows
    db.commit()
    return _ds(d)


@router.delete("/datasets/{did}")
def delete_dataset(did: int, db: Session = Depends(get_db)):
    d = db.get(Dataset, did)
    if d:
        db.delete(d); db.commit()
    return {"deleted": True}
