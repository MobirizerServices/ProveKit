"""Dataset versioning, fingerprints and splits.

An experiment compares against another experiment, and that comparison is only meaningful if
both ran over the same data. Nothing enforced that: a dataset could be edited between two
runs and the resulting "regression" was an artefact of the edit, with nothing on screen to
say so. Regression triage (#46) had to guess at it by comparing stored input strings.

Two mechanisms, because they answer different questions:

- **version** — a counter bumped whenever a dataset's contents change. Cheap, monotonic, and
  the thing a human quotes ("we ran against v4").
- **fingerprint** — a content hash of the items themselves. The counter says *something*
  changed; the fingerprint proves whether two runs actually saw identical data, which the
  counter cannot do across a restore, a re-import, or a counter that got reset.

Splits are a plain label on the item rather than a separate table: a dataset is small, and a
`split` column keeps "the whole set" as the default so existing datasets don't silently change
meaning the moment this shipped.
"""
from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from ..models import Dataset, DatasetItem

log = logging.getLogger("provekit.datasets")

TRAIN = "train"
TEST = "test"
UNASSIGNED = ""
VALID_SPLITS = {TRAIN, TEST, UNASSIGNED}


def fingerprint(db: Session, dataset_id: int) -> str:
    """Stable hash of a dataset's contents.

    Ordered by item id and built from (id, input, expected, split) so the hash tracks the
    things an evaluation actually consumes. Item *timestamps* are deliberately excluded — a
    re-import that reproduces the same examples should fingerprint identically, because for
    the purpose of "are these two runs comparable" it is the same dataset.
    """
    rows = (db.query(DatasetItem.id, DatasetItem.input, DatasetItem.expected, DatasetItem.split)
            .filter(DatasetItem.dataset_id == dataset_id)
            .order_by(DatasetItem.id.asc()).all())
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps([row[0], row[1], row[2], row[3]], sort_keys=True).encode())
    return h.hexdigest()[:32]


#: Snapshots retained per dataset (#45). A snapshot holds whole items, so keeping every version
#: of a heavily-edited set would dwarf the set itself. The cap is reported by the API rather than
#: applied silently — a truncated history that looks complete is worse than a short one.
MAX_SNAPSHOTS = 50


def bump(db: Session, dataset_id: int) -> int:
    """Record that a dataset's contents changed. Returns the new version.

    Called by every mutating path. Missing one is the failure mode that matters: a dataset
    that changed without bumping reports itself as unchanged, which is exactly the silent
    invalidation this module exists to prevent.

    Also captures the contents *as of* the new version (#45), so "what did v3 contain?" has an
    answer later. Callers invoke this after staging their change and before committing, so the
    session is flushed first to read what the change actually produced rather than what was
    there before it.
    """
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if ds is None:
        return 0
    ds.version = (ds.version or 1) + 1
    snapshot(db, ds, ds.version)
    return ds.version


def snapshot(db: Session, ds: Dataset, version: int) -> None:
    """Store the dataset's current items as the contents of `version`.

    Best-effort by design: a snapshot is a convenience for reading history, and failing the
    write that changed the data because we couldn't record a copy of it would trade a real
    operation for a bookkeeping one.
    """
    from ..models import DatasetSnapshot
    try:
        db.flush()   # see the staged add/delete, not the pre-change state
        rows = (db.query(DatasetItem)
                .filter(DatasetItem.dataset_id == ds.id)
                .order_by(DatasetItem.id.asc()).all())
        items = [{"id": r.id, "input": r.input, "expected": r.expected,
                  "split": r.split or "", "meta": r.meta or {}} for r in rows]
        # One snapshot per version: a path that bumps twice in a transaction must not leave two.
        existing = (db.query(DatasetSnapshot)
                    .filter(DatasetSnapshot.dataset_id == ds.id,
                            DatasetSnapshot.version == version).first())
        if existing is not None:
            existing.items, existing.item_count = items, len(items)
            existing.fingerprint = fingerprint(db, ds.id)
            return
        db.add(DatasetSnapshot(workspace_id=ds.workspace_id, dataset_id=ds.id, version=version,
                               fingerprint=fingerprint(db, ds.id), item_count=len(items),
                               items=items))
        _prune_snapshots(db, ds.id)
    except Exception:                                   # noqa: BLE001 — see docstring
        log.exception("dataset snapshot failed for dataset %s v%s", ds.id, version)


def _prune_snapshots(db: Session, dataset_id: int) -> None:
    """Keep the newest MAX_SNAPSHOTS versions of a dataset."""
    from ..models import DatasetSnapshot
    keep = [s.id for s in (db.query(DatasetSnapshot.id)
                           .filter(DatasetSnapshot.dataset_id == dataset_id)
                           .order_by(DatasetSnapshot.version.desc())
                           .limit(MAX_SNAPSHOTS).all())]
    if len(keep) < MAX_SNAPSHOTS:
        return
    (db.query(DatasetSnapshot)
     .filter(DatasetSnapshot.dataset_id == dataset_id, DatasetSnapshot.id.notin_(keep))
     .delete(synchronize_session=False))


def pin(db: Session, dataset_id: int | None) -> dict:
    """The provenance an experiment should record about the data it is about to run over."""
    if not dataset_id:
        return {"dataset_version": 0, "dataset_fingerprint": ""}
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    return {"dataset_version": (ds.version if ds else 0) or 0,
            "dataset_fingerprint": fingerprint(db, dataset_id)}


def comparable(a, b) -> tuple[bool, str]:
    """Whether two experiments can be compared, and why not if they can't.

    Returns (ok, reason). An unrecorded pin (version 0 — an experiment from before this
    existed) is reported as unknown rather than assumed fine: "we can't tell" and "they match"
    are different answers, and quietly conflating them is how a bad comparison gets trusted.
    """
    if a.dataset_id != b.dataset_id:
        return False, "different datasets"
    if not a.dataset_fingerprint or not b.dataset_fingerprint:
        return False, "one of these runs predates dataset versioning, so its data is unknown"
    if a.dataset_fingerprint != b.dataset_fingerprint:
        return False, (f"the dataset changed between these runs "
                       f"(v{a.dataset_version} vs v{b.dataset_version})")
    return True, ""


def split_counts(db: Session, dataset_id: int) -> dict[str, int]:
    counts = {TRAIN: 0, TEST: 0, UNASSIGNED: 0}
    for (s,) in db.query(DatasetItem.split).filter(DatasetItem.dataset_id == dataset_id).all():
        counts[s if s in VALID_SPLITS else UNASSIGNED] += 1
    return counts


def assign_split(db: Session, dataset_id: int, ratio: float = 0.2, *, seed: int = 0) -> dict:
    """Deterministically label a test split.

    Hash-based rather than random: the same item lands in the same split on every run and in
    every environment, so re-splitting doesn't quietly move examples across the boundary and
    invalidate every prior comparison. `seed` lets you choose a *different* stable split.
    """
    if not 0.0 < ratio < 1.0:
        raise ValueError("ratio must be between 0 and 1")
    items = db.query(DatasetItem).filter(DatasetItem.dataset_id == dataset_id).all()
    for it in items:
        digest = hashlib.sha256(f"{seed}:{it.id}".encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
        it.split = TEST if bucket < ratio else TRAIN
    bump(db, dataset_id)
    db.commit()
    return split_counts(db, dataset_id)
