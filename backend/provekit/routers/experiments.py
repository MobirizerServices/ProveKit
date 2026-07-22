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


# A row "passes" at or above this score. Most scorers emit 0/1 or a 0..1 fraction, so half-way
# is the only defensible default; a scorer on another scale takes ?pass_at=.
PASS_AT = 0.5
# Rows returned per scorer per direction. The counts stay exact when the lists are cut — nobody
# triages past the first screen, and a 10k-row experiment should not return a 10k-row payload.
TRIAGE_LIMIT = 50


def _num(scores: dict | None, scorer: str) -> float | None:
    """One scorer's value as a float, or None when absent or non-numeric."""
    try:
        return float((scores or {})[scorer])
    except (KeyError, TypeError, ValueError):
        return None


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _index_by_item(rows: list[ExperimentResult]) -> tuple[dict[int, ExperimentResult], int, int]:
    """item_id -> row, plus counts of what could not be indexed.

    An item scored twice in one run gives no way to know which attempt the other run should be
    compared against, so both copies are dropped rather than picking one arbitrarily and
    reporting the difference as if it were a code change.
    """
    by_item: dict[int, ExperimentResult] = {}
    dupes: set[int] = set()
    no_id = 0
    for r in rows:
        if r.item_id is None:
            no_id += 1
        elif r.item_id in by_item:
            dupes.add(r.item_id)
        else:
            by_item[r.item_id] = r
    for i in dupes:
        by_item.pop(i)
    return by_item, no_id, len(dupes)


def _pair_rows(a_rows: list[ExperimentResult], b_rows: list[ExperimentResult]) -> tuple[list, dict, list[str]]:
    """Rows the two runs genuinely share, with an accounting of everything left out.

    Pairing is by item_id only. Pairing by position would happily line up row 7 of one run
    against row 7 of another and report the difference as a regression, which is confident
    nonsense the moment the two runs saw different material — the exact failure this endpoint
    exists to avoid. Rows whose stored input differs under the same item_id mean the dataset
    item itself was edited between the runs; they are dropped for the same reason.
    """
    a_idx, a_no_id, a_dupes = _index_by_item(a_rows)
    b_idx, b_no_id, b_dupes = _index_by_item(b_rows)
    paired, drifted = [], 0
    for i in sorted(a_idx.keys() & b_idx.keys()):
        ra, rb = a_idx[i], b_idx[i]
        if ra.input and rb.input and ra.input != rb.input:
            drifted += 1
        else:
            paired.append((i, ra, rb))

    counts = {"paired": len(paired), "drifted": drifted,
              "only_in_a": len(a_idx.keys() - b_idx.keys()), "only_in_b": len(b_idx.keys() - a_idx.keys()),
              "no_item_id": a_no_id + b_no_id, "duplicate_item_id": a_dupes + b_dupes}
    notes = []
    if drifted:
        notes.append(f"{drifted} item(s) have a different input in the two runs — the dataset item "
                     f"changed between them, so those rows are not comparable and were dropped.")
    if counts["only_in_a"] or counts["only_in_b"]:
        notes.append(f"{counts['only_in_a']} row(s) only in A and {counts['only_in_b']} only in B — "
                     f"an item scored in one run and not the other has nothing to diff against.")
    if counts["no_item_id"]:
        notes.append(f"{counts['no_item_id']} row(s) carry no item id and were skipped; rows are never "
                     f"paired by position, which would compare unrelated examples.")
    if counts["duplicate_item_id"]:
        notes.append(f"{counts['duplicate_item_id']} item(s) were scored more than once in a run — "
                     f"ambiguous which attempt to compare, so they were skipped.")
    return paired, counts, notes


def _triage_scorer(paired: list, scorer: str, pass_at: float, limit: int) -> dict:
    """Per-row movement for one scorer, worst regression first."""
    regressed, improved, unchanged, only_a, only_b = [], [], 0, 0, 0
    for item_id, ra, rb in paired:
        av, bv = _num(ra.scores, scorer), _num(rb.scores, scorer)
        if av is None and bv is None:
            continue
        if av is None:
            only_b += 1   # scored in B only — the scorer was added, not a regression
            continue
        if bv is None:
            only_a += 1   # scored in A only — the scorer stopped running
            continue
        delta = bv - av
        if delta == 0:
            unchanged += 1
            continue
        crossed = ("pass_to_fail" if av >= pass_at > bv else
                   "fail_to_pass" if bv >= pass_at > av else "")
        entry = {"item_id": item_id, "a_score": av, "b_score": bv, "delta": delta, "crossed": crossed,
                 "input": _clip(ra.input or rb.input, 400), "expected": _clip(ra.expected or rb.expected, 400),
                 "a_output": _clip(ra.output, 600), "b_output": _clip(rb.output, 600)}
        (regressed if delta < 0 else improved).append(entry)

    # A pass that became a fail is a break; a 0.9 → 0.7 dip is a degradation. Sorting the breaks
    # to the top, then by size of drop, puts the row that needs a human first.
    regressed.sort(key=lambda r: (r["crossed"] != "pass_to_fail", r["delta"]))
    improved.sort(key=lambda r: (r["crossed"] != "fail_to_pass", -r["delta"]))
    return {"regressed_count": len(regressed), "improved_count": len(improved), "unchanged": unchanged,
            "pass_to_fail": sum(r["crossed"] == "pass_to_fail" for r in regressed),
            "fail_to_pass": sum(r["crossed"] == "fail_to_pass" for r in improved),
            "scored_only_in_a": only_a, "scored_only_in_b": only_b,
            "regressed": regressed[:limit], "improved": improved[:limit],
            "truncated": len(regressed) > limit or len(improved) > limit}


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


@router.get("/{eid}/triage/{other_id}")
def triage_experiments(eid: int, other_id: int, pass_at: float = PASS_AT, limit: int = TRIAGE_LIMIT,
                       db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Which rows regressed — the question a score delta cannot answer.

    /compare says the mean moved by -0.08 and that the move is real. That still leaves someone
    reading the whole result table to find the handful of examples that broke. This pairs rows
    by dataset item and returns, per scorer, what got worse (worst first), what got better, and
    what crossed the pass/fail line, so "what broke" is one request rather than an afternoon.

    Rows that cannot be paired are reported, never guessed at: see `pairing` and `notes`.
    """
    a, b = _get_experiment(db, ws, eid), _get_experiment(db, ws, other_id)
    limit = max(1, min(limit, 500))
    a_rows = db.query(ExperimentResult).filter(ExperimentResult.experiment_id == a.id).all()
    b_rows = db.query(ExperimentResult).filter(ExperimentResult.experiment_id == b.id).all()

    out = {"a": {"id": a.id, "name": a.name, "dataset_id": a.dataset_id, "created_at": iso_utc(a.created_at)},
           "b": {"id": b.id, "name": b.name, "dataset_id": b.dataset_id, "created_at": iso_utc(b.created_at)},
           "pass_at": pass_at, "comparable": False, "warning": "", "notes": [],
           "pairing": {"paired": 0, "drifted": 0, "only_in_a": 0, "only_in_b": 0,
                       "no_item_id": 0, "duplicate_item_id": 0},
           "scorers": {}}

    if a.dataset_id != b.dataset_id:
        # Item ids are only meaningful within a dataset, so a row-level diff across two of them
        # would be comparing unrelated examples. Refuse rather than produce a plausible table.
        out["warning"] = ("These experiments ran against different datasets, so their rows are not "
                          "the same examples and cannot be diffed row by row.")
        return out

    paired, counts, notes = _pair_rows(a_rows, b_rows)
    out["pairing"], out["notes"], out["comparable"] = counts, notes, bool(paired)
    if not paired:
        out["warning"] = ("No dataset items were scored in both runs, so there is nothing to diff "
                          "row by row.")
        return out

    scorers = {k for _, ra, rb in paired for k in (list(ra.scores or {}) + list(rb.scores or {}))}
    out["scorers"] = {name: _triage_scorer(paired, name, pass_at, limit) for name in sorted(scorers)}
    return out


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
