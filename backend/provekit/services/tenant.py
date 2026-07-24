"""Tenant lifecycle: suspend, and delete for real (#82).

**Why this discovers models instead of listing them.** Deleting a project used to run down a
hand-written list of tables. That list drifted twice — flows outlived their project once, and by
the time this was written thirteen workspace-scoped tables were being left behind, including
`provider_connections`, which holds sealed provider API keys. A deletion that leaves the
customer's credentials in the database is not a deletion, and the failure is silent: the project
vanishes from the UI and the rows stay.

So the set is derived from the mapper — every model carrying `workspace_id` is purged unless it
is named in `KEEP`. Adding a new tenant-scoped table now opts into deletion by default, and
`test_tenant.py` fails if a model is neither purged nor deliberately kept. The safe direction is
the automatic one.

**Suspension** is a read-only state, not a soft delete. A suspended project still serves its data
so an owner can export it; it refuses ingest and mutation so it stops accumulating more.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models

log = logging.getLogger("provekit.tenant")

#: Deliberately survives a tenant purge.
#:
#: `AuditLog` is the record *that the deletion happened*, and services/audit.py already snapshots
#: the actor and target so a row outlives its subject. Deleting the audit trail as part of the
#: thing it audits would leave nothing attesting the tenant ever existed or was removed — the
#: opposite of what an operator needs after a deletion request.
KEEP: frozenset[str] = frozenset({"AuditLog"})


def scoped_models() -> list[type]:
    """Every mapped model carrying a `workspace_id`, discovered from the metadata."""
    out = []
    for mapper in models.Base.registry.mappers:
        cls = mapper.class_
        if "workspace_id" in mapper.columns:
            out.append(cls)
    return sorted(out, key=lambda c: c.__name__)


def purgeable() -> list[type]:
    return [m for m in scoped_models() if m.__name__ not in KEEP]


def _order(models_: list[type]) -> list[type]:
    """Children before parents, so a foreign key can't block a delete.

    Only two real dependencies exist inside a tenant (results→experiments, items/snapshots→
    datasets); everything else is independent. Naming them explicitly is clearer than inferring
    an order from the FK graph for a handful of tables.
    """
    first = ["ExperimentResult", "DatasetItem", "DatasetSnapshot", "FlowRun", "FlowVersion",
             "SpanNote", "ReplayRun"]
    rank = {name: i for i, name in enumerate(first)}
    return sorted(models_, key=lambda m: (rank.get(m.__name__, len(first)), m.__name__))


def purge(db: Session, workspace_id: int) -> dict[str, int]:
    """Delete every tenant-scoped row for a workspace. Returns rows removed per table.

    Does not commit — the caller decides when the deletion becomes durable, so the workspace row
    and its contents go in one transaction.
    """
    removed: dict[str, int] = {}
    for model in _order(purgeable()):
        n = (db.query(model)
             .filter(model.workspace_id == workspace_id)
             .delete(synchronize_session=False))
        if n:
            removed[model.__tablename__] = n
    return removed


def remaining(db: Session, workspace_id: int) -> dict[str, int]:
    """Tenant-scoped rows still present. Used to *verify* a purge rather than assume it."""
    left: dict[str, int] = {}
    for model in purgeable():
        n = db.query(model).filter(model.workspace_id == workspace_id).count()
        if n:
            left[model.__tablename__] = n
    return left


def is_suspended(ws: models.Workspace | None) -> bool:
    return bool(ws is not None and ws.suspended_at)
