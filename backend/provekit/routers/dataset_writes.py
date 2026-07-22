"""Key-authed dataset writes — the half of `/v1/datasets` that only ever had a read side.

`/v1/datasets` (project key) could list datasets and their items, but every way to *add* to a
dataset was cookie-authed, i.e. the portal UI. That left the loop the MCP debug channel exists
for — find a failing trace, put it in the regression set, run the eval — needing a browser in
the middle. These are the same two append operations `routers/datasets.py` exposes to the
portal, resolved against the workspace the key belongs to.

Deletes and edits deliberately stay portal-only. A project key lives in CI config and in MCP
client config; nothing holding one should be able to drop a curated dataset or silently rewrite
the `expected` that past experiments were scored against.

Row shapes are imported from `datasets` rather than restated, so the two doors onto one table
cannot drift into returning different JSON for the same row.
"""
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Dataset, DatasetItem
from ..services.workspace import workspace_from_key
from .datasets import _DatasetIn, _dataset_row, _get_dataset, _item_row, _ItemIn

key_router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@key_router.post("")
def create_dataset_by_key(data: _DatasetIn, request: Request, db: Session = Depends(get_db),
                          authorization: str | None = Header(default=None)):
    """Create an empty dataset in the key's project."""
    ws = workspace_from_key(db, request, authorization)
    d = Dataset(workspace_id=ws.id, name=data.name[:160], description=data.description)
    db.add(d)
    db.commit()
    return _dataset_row(d, 0)


@key_router.post("/{dataset_id}/items")
def add_item_by_key(dataset_id: int, data: _ItemIn, request: Request, db: Session = Depends(get_db),
                    authorization: str | None = Header(default=None)):
    """Append one {input, expected} item. `meta` carries provenance (trace_id/span_id/source)
    so a promoted item can be traced back to the run it came from."""
    ws = workspace_from_key(db, request, authorization)
    _get_dataset(db, ws, dataset_id)   # 404s across tenants before anything is written
    it = DatasetItem(workspace_id=ws.id, dataset_id=dataset_id, input=data.input,
                     expected=data.expected, meta=data.meta or {})
    db.add(it)
    db.commit()
    return _item_row(it)
