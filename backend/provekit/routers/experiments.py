"""Experiments — offline evaluation runs. The SDK's pk.evaluate() creates an experiment,
runs a target over a dataset, scores each output, and posts the results here (project key).
The portal lists experiments with per-scorer means so you can compare runs and catch a
regression before it ships."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Experiment, ExperimentResult, Workspace, iso_utc
from ..services.workspace import current_workspace, workspace_from_key

router = APIRouter(prefix="/api/experiments", tags=["experiments"])
key_router = APIRouter(prefix="/v1/experiments", tags=["experiments"])


class _ExperimentIn(BaseModel):
    name: str
    dataset_id: int | None = None


class _ResultIn(BaseModel):
    input: str = ""
    output: str = ""
    expected: str = ""
    item_id: int | None = None
    scores: dict = {}


def _summarize(results: list[ExperimentResult]) -> dict:
    """Per-scorer means + an overall mean across every score value."""
    agg: dict[str, list[float]] = {}
    for r in results:
        for k, v in (r.scores or {}).items():
            try:
                a = agg.setdefault(k, [0.0, 0.0])
                a[0] += float(v)
                a[1] += 1
            except (TypeError, ValueError):
                continue
    per = {k: (s / n) for k, (s, n) in agg.items() if n}
    total_sum = sum(s for s, _ in agg.values())
    total_n = sum(n for _, n in agg.values())
    return {"result_count": len(results),
            "scorer_means": per,
            "mean_score": (total_sum / total_n) if total_n else None}


def _experiment_row(db: Session, e: Experiment) -> dict:
    results = db.query(ExperimentResult).filter(ExperimentResult.experiment_id == e.id).all()
    return {"id": e.id, "name": e.name, "dataset_id": e.dataset_id,
            "created_at": iso_utc(e.created_at), **_summarize(results)}


def _get_experiment(db: Session, ws: Workspace, eid: int) -> Experiment:
    e = db.get(Experiment, eid)
    if not e or e.workspace_id != ws.id:
        raise HTTPException(404, "Experiment not found")
    return e


def _create(db: Session, ws: Workspace, data: _ExperimentIn) -> dict:
    e = Experiment(workspace_id=ws.id, name=data.name[:160], dataset_id=data.dataset_id)
    db.add(e)
    db.commit()
    return {"id": e.id, "name": e.name, "dataset_id": e.dataset_id, "created_at": iso_utc(e.created_at)}


def _add_result(db: Session, ws: Workspace, eid: int, data: _ResultIn) -> dict:
    _get_experiment(db, ws, eid)
    r = ExperimentResult(workspace_id=ws.id, experiment_id=eid, item_id=data.item_id,
                         input=data.input, output=data.output, expected=data.expected,
                         scores=data.scores or {})
    db.add(r)
    db.commit()
    return {"id": r.id, "experiment_id": eid, "scores": r.scores}


# ---- portal (cookie) ----
@router.post("")
def create_experiment(data: _ExperimentIn, db: Session = Depends(get_db),
                      ws: Workspace = Depends(current_workspace)):
    return _create(db, ws, data)


@router.get("")
def list_experiments(dataset_id: int | None = None, db: Session = Depends(get_db),
                     ws: Workspace = Depends(current_workspace)):
    """List experiments with their per-scorer means. Filter by dataset_id to compare runs
    on the same dataset side by side."""
    q = db.query(Experiment).filter(Experiment.workspace_id == ws.id)
    if dataset_id is not None:
        q = q.filter(Experiment.dataset_id == dataset_id)
    return [_experiment_row(db, e) for e in q.order_by(Experiment.id.desc()).all()]


@router.post("/{eid}/results")
def add_result(eid: int, data: _ResultIn, db: Session = Depends(get_db),
               ws: Workspace = Depends(current_workspace)):
    return _add_result(db, ws, eid, data)


@router.get("/{eid}")
def get_experiment(eid: int, db: Session = Depends(get_db),
                   ws: Workspace = Depends(current_workspace)):
    e = _get_experiment(db, ws, eid)
    results = (db.query(ExperimentResult).filter(ExperimentResult.experiment_id == e.id)
               .order_by(ExperimentResult.id.asc()).all())
    return {**_experiment_row(db, e),
            "results": [{"id": r.id, "item_id": r.item_id, "input": r.input, "output": r.output,
                         "expected": r.expected, "scores": r.scores} for r in results]}


@router.delete("/{eid}")
def delete_experiment(eid: int, db: Session = Depends(get_db),
                      ws: Workspace = Depends(current_workspace)):
    e = _get_experiment(db, ws, eid)
    db.query(ExperimentResult).filter(ExperimentResult.experiment_id == e.id).delete(synchronize_session=False)
    db.delete(e)
    db.commit()
    return {"ok": True}


# ---- SDK (project key): pk.evaluate() creates an experiment and posts results ----
@key_router.post("")
def create_experiment_by_key(data: _ExperimentIn, request: Request, db: Session = Depends(get_db),
                             authorization: str | None = Header(default=None)):
    return _create(db, workspace_from_key(db, request, authorization), data)


@key_router.post("/{eid}/results")
def add_result_by_key(eid: int, data: _ResultIn, request: Request, db: Session = Depends(get_db),
                      authorization: str | None = Header(default=None)):
    return _add_result(db, workspace_from_key(db, request, authorization), eid, data)


@key_router.get("/{eid}")
def get_experiment_by_key(eid: int, request: Request, db: Session = Depends(get_db),
                          authorization: str | None = Header(default=None)):
    ws = workspace_from_key(db, request, authorization)
    return _experiment_row(db, _get_experiment(db, ws, eid))
