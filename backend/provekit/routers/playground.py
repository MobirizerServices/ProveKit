"""Interactive debugging: re-run a captured LLM call with edited prompt/params (the playground),
and manage the per-project provider connections (BYO keys, sealed at rest) it uses.

The trace replay harness (POST /api/replay) is added in a later milestone and reuses the same
connections + llm_client here.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ProviderConnection, Workspace, _now, iso_utc
from ..services import limits
from ..services.llm_client import LLMError, complete
from ..services.sealing import mask_key, seal, unseal
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api", tags=["playground"])

_PROVIDERS = {"openai", "anthropic", "openai_compatible", "mock"}
_MAX_TOKENS_CAP = 4096   # hard ceiling per run so an edit can't run up a huge bill


# ---- provider connections (BYO keys) ----
class _ConnIn(BaseModel):
    provider: str
    label: str = ""
    key: str = ""
    base_url: str = ""


def _conn_row(c: ProviderConnection) -> dict:
    return {"id": c.id, "provider": c.provider, "label": c.label, "key_hint": c.key_hint,
            "base_url": c.base_url, "last_used_at": iso_utc(c.last_used_at),
            "created_at": iso_utc(c.created_at)}


@router.get("/connections")
def list_connections(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(ProviderConnection).filter(ProviderConnection.workspace_id == ws.id)
            .order_by(ProviderConnection.id.desc()).all())
    return [_conn_row(c) for c in rows]


@router.post("/connections")
def create_connection(data: _ConnIn, db: Session = Depends(get_db),
                      ws: Workspace = Depends(current_workspace)):
    provider = data.provider.lower()
    if provider not in _PROVIDERS:
        raise HTTPException(422, f"provider must be one of {sorted(_PROVIDERS)}")
    if provider != "mock" and not data.key.strip():
        raise HTTPException(422, "an API key is required for this provider")
    if provider == "openai_compatible" and not data.base_url.strip():
        raise HTTPException(422, "base_url is required for an OpenAI-compatible connection")
    key = data.key.strip()
    c = ProviderConnection(
        workspace_id=ws.id, provider=provider,
        label=(data.label or provider)[:120],
        key_sealed=seal(key) if key else "",
        key_hint=mask_key(key) if key else "",
        base_url=data.base_url.strip()[:300])
    db.add(c); db.commit(); db.refresh(c)
    return _conn_row(c)


@router.delete("/connections/{cid}")
def delete_connection(cid: int, db: Session = Depends(get_db),
                      ws: Workspace = Depends(current_workspace)):
    c = db.get(ProviderConnection, cid)
    if not c or c.workspace_id != ws.id:
        raise HTTPException(404, "Connection not found")
    db.delete(c); db.commit()
    return {"ok": True}


# ---- the playground: re-run one LLM call ----
class _Msg(BaseModel):
    role: str
    content: str


class _RunIn(BaseModel):
    model: str
    messages: list[_Msg]
    params: dict = {}
    connection_id: int | None = None
    provider: str | None = None      # allows provider="mock" with no stored connection
    from_span_id: str | None = None  # provenance: which captured span this re-runs


def _resolve(db: Session, ws: Workspace, data: _RunIn) -> tuple[str, str, str]:
    """Return (provider, api_key, base_url) for the run, from a stored connection or a keyless
    mock. Marks the connection used."""
    if data.connection_id is not None:
        c = db.get(ProviderConnection, data.connection_id)
        if not c or c.workspace_id != ws.id:
            raise HTTPException(404, "Connection not found")
        c.last_used_at = _now(); db.commit()
        key = unseal(c.key_sealed) if c.key_sealed else ""
        return c.provider, key, c.base_url
    if (data.provider or "").lower() == "mock":
        return "mock", "", ""
    raise HTTPException(422, "connection_id is required (or use provider='mock')")


@router.post("/playground/run")
async def playground_run(data: _RunIn, db: Session = Depends(get_db),
                         ws: Workspace = Depends(current_workspace)):
    limits.check_playground_rate(ws.id)
    if not data.messages:
        raise HTTPException(422, "at least one message is required")
    params = dict(data.params or {})
    if params.get("max_tokens"):
        params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
    provider, api_key, base_url = _resolve(db, ws, data)
    messages = [{"role": m.role, "content": m.content} for m in data.messages]
    t0 = time.monotonic()
    try:
        result = await complete(provider, data.model, messages, params,
                                api_key=api_key, base_url=base_url)
    except LLMError as e:
        raise HTTPException(502, str(e))
    result["latency_ms"] = round((time.monotonic() - t0) * 1000)
    result["provider"] = provider
    result["model"] = data.model
    return result
