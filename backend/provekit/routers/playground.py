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
from ..models import DatasetItem, Experiment, ExperimentResult, Prompt, ProviderConnection, Workspace, _now, iso_utc
from ..scorers import run_scorers
from ..services import limits, pricing
from ..services.llm_client import LLMError, complete, judge
from ..services.replay import reconstruct
from ..services.replay import webhook as replay_webhook
from ..services.sealing import mask_key, seal, unseal
from ..services.workspace import current_workspace
from .experiments import _experiment_row

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
    limits.check_spend_cap(ws.id)
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
    limits.record_spend(ws.id, pricing.estimate(data.model, result["usage"].get("input_tokens"),
                                                result["usage"].get("output_tokens")))
    return result


# ---- the replay harness: fork a trace at a span, re-run the flow with the edit ----
class _ReplayIn(BaseModel):
    origin_trace_id: str
    fork_span_id: str
    model: str
    messages: list[_Msg]
    params: dict = {}
    connection_id: int | None = None
    provider: str | None = None
    mode: str = "reconstructed"      # reconstructed | webhook


@router.post("/replay")
async def replay(data: _ReplayIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    if not data.messages:
        raise HTTPException(422, "at least one message is required")
    params = dict(data.params or {})
    if params.get("max_tokens"):
        params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
    messages = [{"role": m.role, "content": m.content} for m in data.messages]
    try:
        if data.mode == "webhook":
            return await replay_webhook(db, ws, data.origin_trace_id, data.fork_span_id,
                                        {"model": data.model, "messages": messages, "params": params})
        provider, api_key, base_url = _resolve(db, ws, _RunIn(
            model=data.model, messages=data.messages, params=params,
            connection_id=data.connection_id, provider=data.provider))
        return await reconstruct(db, ws, data.origin_trace_id, data.fork_span_id,
                                 data.model, messages, params,
                                 provider=provider, api_key=api_key, base_url=base_url)
    except LLMError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---- saved prompt versions ----
class _PromptIn(BaseModel):
    name: str
    model: str = ""
    messages: list[_Msg] = []
    params: dict = {}


def _prompt_row(p: Prompt) -> dict:
    return {"id": p.id, "name": p.name, "version": p.version, "model": p.model,
            "messages": p.messages, "params": p.params, "created_at": iso_utc(p.created_at)}


@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(Prompt).filter(Prompt.workspace_id == ws.id)
            .order_by(Prompt.id.desc()).all())
    return [_prompt_row(p) for p in rows]


@router.post("/prompts")
def save_prompt(data: _PromptIn, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    if not data.name.strip():
        raise HTTPException(422, "a name is required")
    # auto-increment the version for this name within the project
    prev = (db.query(Prompt).filter(Prompt.workspace_id == ws.id, Prompt.name == data.name.strip())
            .order_by(Prompt.version.desc()).first())
    p = Prompt(workspace_id=ws.id, name=data.name.strip()[:160], version=(prev.version + 1 if prev else 1),
               model=data.model, messages=[m.model_dump() for m in data.messages], params=data.params)
    db.add(p); db.commit(); db.refresh(p)
    return _prompt_row(p)


@router.delete("/prompts/{pid}")
def delete_prompt(pid: int, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    p = db.get(Prompt, pid)
    if not p or p.workspace_id != ws.id:
        raise HTTPException(404, "Prompt not found")
    db.delete(p); db.commit()
    return {"ok": True}


# ---- run an edited prompt over a dataset → a scored experiment ----
class _ExpIn(BaseModel):
    dataset_id: int
    name: str = ""
    model: str
    messages: list[_Msg]
    params: dict = {}
    connection_id: int | None = None
    provider: str | None = None
    scorers: list[str] = ["exact_match", "contains"]


_EXP_ITEM_CAP = 100   # bound cost: score at most N items per run


def _fill(messages: list[dict], item_input: str, item_expected: str) -> list[dict]:
    """Substitute {{input}} / {{expected}} in the prompt for a dataset item. If the prompt
    references neither, append the item input as a trailing user message so it still runs."""
    out, has_input = [], False
    for m in messages:
        c = m["content"]
        if "{{input}}" in c:
            has_input = True
        c = c.replace("{{input}}", item_input).replace("{{expected}}", item_expected)
        out.append({"role": m["role"], "content": c})
    if not has_input:
        out.append({"role": "user", "content": item_input})
    return out


@router.post("/playground/experiment")
async def playground_experiment(data: _ExpIn, db: Session = Depends(get_db),
                                ws: Workspace = Depends(current_workspace)):
    limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    items = (db.query(DatasetItem)
             .filter(DatasetItem.workspace_id == ws.id, DatasetItem.dataset_id == data.dataset_id)
             .order_by(DatasetItem.id.asc()).limit(_EXP_ITEM_CAP).all())
    if not items:
        raise HTTPException(404, "dataset is empty or not found")
    params = dict(data.params or {})
    if params.get("max_tokens"):
        params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
    provider, api_key, base_url = _resolve(db, ws, _RunIn(
        model=data.model, messages=data.messages, params=params,
        connection_id=data.connection_id, provider=data.provider))
    base_msgs = [{"role": m.role, "content": m.content} for m in data.messages]

    exp = Experiment(workspace_id=ws.id, name=(data.name or f"Playground · {data.model}")[:160],
                     dataset_id=data.dataset_id)
    db.add(exp); db.commit(); db.refresh(exp)
    try:
        want_judge = "llm_judge" in data.scorers
        sync_scorers = [s for s in data.scorers if s != "llm_judge"]
        for it in items:
            msgs = _fill(base_msgs, it.input, it.expected)
            r = await complete(provider, data.model, msgs, params, api_key=api_key, base_url=base_url)
            limits.record_spend(ws.id, pricing.estimate(data.model, r["usage"].get("input_tokens"),
                                                        r["usage"].get("output_tokens")))
            scores = run_scorers(sync_scorers, r["output"], it.expected)
            if want_judge:
                scores["llm_judge"] = await judge(provider, data.model, it.input, it.expected,
                                                  r["output"], api_key=api_key, base_url=base_url)
            db.add(ExperimentResult(workspace_id=ws.id, experiment_id=exp.id, item_id=it.id,
                                    input=it.input, output=r["output"], expected=it.expected, scores=scores))
        db.commit()
    except LLMError as e:
        db.commit()   # keep whatever scored before the failure
        raise HTTPException(502, str(e))
    return _experiment_row(db, exp)
