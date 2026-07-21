"""Experiments — offline evaluation runs. The SDK's pk.evaluate() creates an experiment,
runs a target over a dataset, scores each output, and posts the results here (project key).
The portal lists experiments with per-scorer means so you can compare runs and catch a
regression before it ships."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Experiment, ExperimentResult, Workspace, iso_utc
from ..services import stats
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


def _scorer_values(results: list[ExperimentResult]) -> dict[str, list[float]]:
    """Per-scorer score lists. Non-numeric values are skipped, not coerced to zero."""
    agg: dict[str, list[float]] = {}
    for r in results:
        for k, v in (r.scores or {}).items():
            try:
                agg.setdefault(k, []).append(float(v))
            except (TypeError, ValueError):
                continue
    return agg


def _summarize(results: list[ExperimentResult]) -> dict:
    """Per-scorer means, plus the spread around them.

    A mean on its own can't tell 0.82-over-20-examples from 0.82-over-2000, so every scorer
    also reports n, standard deviation and a 95% interval.
    """
    agg = _scorer_values(results)
    per = {k: (sum(v) / len(v)) for k, v in agg.items() if v}
    flat = [x for v in agg.values() for x in v]
    return {"result_count": len(results),
            "scorer_means": per,
            "scorer_stats": {k: stats.summarize(v) for k, v in agg.items()},
            "mean_score": (sum(flat) / len(flat)) if flat else None}


def _pairs_by_item(a_rows: list[ExperimentResult], b_rows: list[ExperimentResult],
                   scorer: str) -> list[tuple[float, float]]:
    """(a, b) score pairs for items scored in both runs.

    Two runs over one dataset score the same items, so pairing on item_id removes item
    difficulty from the comparison — the difference between detecting a real 5% gain and
    losing it in the noise of how hard each example happens to be.
    """
    def index(rows):
        out = {}
        for r in rows:
            if r.item_id is None:
                continue
            try:
                out[r.item_id] = float((r.scores or {})[scorer])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    a_idx, b_idx = index(a_rows), index(b_rows)
    return [(a_idx[i], b_idx[i]) for i in sorted(a_idx.keys() & b_idx.keys())]


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


@router.get("/{eid}/compare/{other_id}")
def compare_experiments(eid: int, other_id: int, db: Session = Depends(get_db),
                        ws: Workspace = Depends(current_workspace)):
    """Is the difference between two experiments real, or is it noise?

    Returns per-scorer means with intervals, the delta, and a permutation-test p-value —
    paired on item id where the two runs scored the same examples.
    """
    a, b = _get_experiment(db, ws, eid), _get_experiment(db, ws, other_id)
    a_rows = db.query(ExperimentResult).filter(ExperimentResult.experiment_id == a.id).all()
    b_rows = db.query(ExperimentResult).filter(ExperimentResult.experiment_id == b.id).all()
    a_vals, b_vals = _scorer_values(a_rows), _scorer_values(b_rows)

    scorers = {}
    for name in sorted(set(a_vals) | set(b_vals)):
        pairs = _pairs_by_item(a_rows, b_rows, name)
        scorers[name] = stats.compare(a_vals.get(name, []), b_vals.get(name, []),
                                      pairs=pairs or None)
    warning = ""
    if a.dataset_id != b.dataset_id:
        # Scores over different material aren't comparable, whatever the arithmetic says.
        warning = ("These experiments ran on different datasets, so the comparison measures "
                   "the datasets as much as the runs.")
    return {"a": {"id": a.id, "name": a.name, "dataset_id": a.dataset_id,
                  "created_at": iso_utc(a.created_at)},
            "b": {"id": b.id, "name": b.name, "dataset_id": b.dataset_id,
                  "created_at": iso_utc(b.created_at)},
            "alpha": stats.ALPHA, "warning": warning, "scorers": scorers}


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
