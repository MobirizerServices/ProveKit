"""Datasets — named collections of {input, expected} examples that offline evaluations run
against. Curated by hand in the portal (cookie auth) or pulled by the SDK (project key), and
seedable straight from a captured production trace."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Dataset, DatasetItem, DatasetSnapshot, Run, Workspace, iso_utc
from ..services import datasets as datasets_svc
from ..services import errors
from ..services.workspace import current_workspace, workspace_from_key

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
key_router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


class _DatasetIn(BaseModel):
    name: str
    description: str = ""


class _ItemIn(BaseModel):
    input: str
    expected: str = ""
    meta: dict = {}


class _FromTraceIn(BaseModel):
    trace_id: str
    expected: str = ""


def _dataset_row(d: Dataset, count: int) -> dict:
    return {"id": d.id, "name": d.name, "description": d.description,
            "item_count": count, "version": d.version or 1,
            "created_at": iso_utc(d.created_at)}


def _item_row(it: DatasetItem) -> dict:
    return {"id": it.id, "dataset_id": it.dataset_id, "input": it.input,
            "expected": it.expected, "meta": it.meta, "split": it.split or "",
            "created_at": iso_utc(it.created_at)}


class _SplitIn(BaseModel):
    ratio: float = 0.2
    seed: int = 0


@router.post("/{dataset_id}/split")
def assign_split(dataset_id: int, data: _SplitIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    """Deterministically label a train/test split.

    Hash-based, not random: the same item lands in the same split every time, so re-splitting
    can't quietly move examples across the boundary and invalidate every earlier comparison.
    """
    _get_dataset(db, ws, dataset_id)
    try:
        counts = datasets_svc.assign_split(db, dataset_id, data.ratio, seed=data.seed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"dataset_id": dataset_id, "counts": counts}


@router.get("/{dataset_id}/version")
def dataset_version(dataset_id: int, db: Session = Depends(get_db),
                    ws: Workspace = Depends(current_workspace)):
    """Version, content fingerprint and split breakdown — the provenance an experiment pins."""
    d = _get_dataset(db, ws, dataset_id)
    return {"dataset_id": dataset_id, "version": d.version or 1,
            "fingerprint": datasets_svc.fingerprint(db, dataset_id),
            "splits": datasets_svc.split_counts(db, dataset_id)}


@router.get("/{dataset_id}/versions")
def dataset_versions(dataset_id: int, db: Session = Depends(get_db),
                     ws: Workspace = Depends(current_workspace)):
    """The version history: what each version contained, without the contents themselves (#45).

    `retained` names the cap so a history that has been pruned can't be mistaken for the whole
    life of the dataset, and `live_version` says which entry is the dataset as it stands now.
    """
    d = _get_dataset(db, ws, dataset_id)
    rows = (db.query(DatasetSnapshot)
            .filter(DatasetSnapshot.dataset_id == dataset_id)
            .order_by(DatasetSnapshot.version.desc()).all())
    return {
        "dataset_id": dataset_id,
        "live_version": d.version or 1,
        "retained": datasets_svc.MAX_SNAPSHOTS,
        "oldest_retained": rows[-1].version if rows else None,
        "versions": [{"version": s.version, "fingerprint": s.fingerprint,
                      "item_count": s.item_count, "created_at": iso_utc(s.created_at)}
                     for s in rows],
    }


@router.get("/{dataset_id}/versions/{version}")
def dataset_version_contents(dataset_id: int, version: int, db: Session = Depends(get_db),
                             ws: Workspace = Depends(current_workspace)):
    """The items a dataset actually held at `version` — the question a pinned experiment asks."""
    _get_dataset(db, ws, dataset_id)
    s = (db.query(DatasetSnapshot)
         .filter(DatasetSnapshot.dataset_id == dataset_id,
                 DatasetSnapshot.version == version).first())
    if s is None:
        raise HTTPException(404, errors.dataset_version_missing(dataset_id, version,
                                                                datasets_svc.MAX_SNAPSHOTS))
    return {"dataset_id": dataset_id, "version": s.version, "fingerprint": s.fingerprint,
            "item_count": s.item_count, "created_at": iso_utc(s.created_at),
            "items": s.items or []}


def _get_dataset(db: Session, ws: Workspace, dataset_id: int) -> Dataset:
    d = db.get(Dataset, dataset_id)
    if not d or d.workspace_id != ws.id:
        raise HTTPException(404, "Dataset not found")
    return d


def _counts(db: Session, ws: Workspace) -> dict:
    return dict(db.query(DatasetItem.dataset_id, func.count(DatasetItem.id))
                .filter(DatasetItem.workspace_id == ws.id)
                .group_by(DatasetItem.dataset_id).all())


# ---- portal (cookie) ----
@router.post("")
def create_dataset(data: _DatasetIn, db: Session = Depends(get_db),
                   ws: Workspace = Depends(current_workspace)):
    d = Dataset(workspace_id=ws.id, name=data.name[:160], description=data.description)
    db.add(d)
    db.commit()
    return _dataset_row(d, 0)


@router.get("")
def list_datasets(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    counts = _counts(db, ws)
    rows = db.query(Dataset).filter(Dataset.workspace_id == ws.id).order_by(Dataset.id.desc()).all()
    return [_dataset_row(d, counts.get(d.id, 0)) for d in rows]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    d = _get_dataset(db, ws, dataset_id)
    items = (db.query(DatasetItem).filter(DatasetItem.dataset_id == d.id)
             .order_by(DatasetItem.id.asc()).all())
    return {**_dataset_row(d, len(items)), "items": [_item_row(i) for i in items]}


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: int, db: Session = Depends(get_db),
                   ws: Workspace = Depends(current_workspace)):
    d = _get_dataset(db, ws, dataset_id)
    db.query(DatasetItem).filter(DatasetItem.dataset_id == d.id).delete(synchronize_session=False)
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.post("/{dataset_id}/items")
def add_item(dataset_id: int, data: _ItemIn, db: Session = Depends(get_db),
             ws: Workspace = Depends(current_workspace)):
    _get_dataset(db, ws, dataset_id)
    it = DatasetItem(workspace_id=ws.id, dataset_id=dataset_id, input=data.input,
                     expected=data.expected, meta=data.meta or {})
    db.add(it)
    datasets_svc.bump(db, dataset_id)
    db.commit()
    return _item_row(it)


@router.post("/{dataset_id}/items/from-trace")
def add_item_from_trace(dataset_id: int, data: _FromTraceIn, db: Session = Depends(get_db),
                        ws: Workspace = Depends(current_workspace)):
    """Seed a dataset item from a captured trace: the root span's input becomes the item
    input, its output the expected (unless overridden)."""
    _get_dataset(db, ws, dataset_id)
    root = (db.query(Run).filter(Run.workspace_id == ws.id, Run.trace_id == data.trace_id,
                                 Run.parent_span_id == "").first())
    if not root:
        raise HTTPException(404, "Trace not found")
    inp = (root.request or {}).get("input", "") if isinstance(root.request, dict) else ""
    out = (root.result or {}).get("text") or "" if isinstance(root.result, dict) else ""
    it = DatasetItem(workspace_id=ws.id, dataset_id=dataset_id, input=inp,
                     expected=data.expected or out, meta={"trace_id": data.trace_id})
    db.add(it)
    datasets_svc.bump(db, dataset_id)
    db.commit()
    return _item_row(it)


@router.delete("/{dataset_id}/items/{item_id}")
def delete_item(dataset_id: int, item_id: int, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    _get_dataset(db, ws, dataset_id)
    it = db.get(DatasetItem, item_id)
    if not it or it.workspace_id != ws.id or it.dataset_id != dataset_id:
        raise HTTPException(404, "Item not found")
    db.delete(it)
    datasets_svc.bump(db, dataset_id)
    db.commit()
    return {"ok": True}


# ---- SDK (project key) read: pk.evaluate() pulls a dataset's items ----
@key_router.get("")
def list_datasets_by_key(request: Request, db: Session = Depends(get_db),
                         authorization: str | None = Header(default=None)):
    ws = workspace_from_key(db, request, authorization)
    counts = _counts(db, ws)
    rows = db.query(Dataset).filter(Dataset.workspace_id == ws.id).order_by(Dataset.id.desc()).all()
    return [_dataset_row(d, counts.get(d.id, 0)) for d in rows]


@key_router.get("/{dataset_id}/items")
def list_items_by_key(dataset_id: int, request: Request, db: Session = Depends(get_db),
                      authorization: str | None = Header(default=None)):
    ws = workspace_from_key(db, request, authorization)
    _get_dataset(db, ws, dataset_id)
    items = (db.query(DatasetItem).filter(DatasetItem.dataset_id == dataset_id)
             .order_by(DatasetItem.id.asc()).all())
    return [_item_row(i) for i in items]
