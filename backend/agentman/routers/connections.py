"""Connections (providers): llm | mcp | agent. Secrets are masked in responses and
preserved on update when the client sends a masked/empty key."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Connection, Workspace, iso_utc
from ..services.assertions import get_path
from ..services.masking import MASK, mask_headers, mask_value
from ..services.netguard import BlockedURL, guard_url
from ..services.providers.mcp_client import MCPSession
from ..services.workspace import current_workspace


def _guard_url(url: str) -> None:
    """Shared SSRF guard (services.netguard), surfaced as a 400 for router callers."""
    try:
        guard_url(url)
    except BlockedURL as exc:
        raise HTTPException(400, str(exc))


def _get(db: Session, ws: Workspace, cid: int) -> Connection:
    """Fetch a connection scoped to the workspace (404 across workspaces)."""
    c = db.get(Connection, cid)
    if not c or c.workspace_id != ws.id:
        raise HTTPException(404, "Connection not found")
    return c


router = APIRouter(prefix="/api/connections", tags=["connections"])


def _public(c: Connection) -> dict:
    cfg = dict(c.config or {})
    if cfg.get("api_key"):
        cfg["api_key"] = mask_value(cfg["api_key"])
        cfg["has_key"] = True
    hdrs = cfg.get("headers")
    if isinstance(hdrs, dict) and hdrs:
        cfg["headers"] = mask_headers(hdrs)
    return {"id": c.id, "name": c.name, "kind": c.kind, "config": cfg,
            "created_at": iso_utc(c.created_at)}


class ConnectionIn(BaseModel):
    name: str
    kind: str  # llm | mcp | agent
    config: dict = {}


@router.get("")
def list_connections(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    return [_public(c) for c in db.query(Connection).filter(Connection.workspace_id == ws.id).order_by(Connection.id).all()]


@router.post("")
def create_connection(payload: ConnectionIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    c = Connection(workspace_id=ws.id, name=payload.name, kind=payload.kind, config=payload.config or {})
    db.add(c); db.commit(); db.refresh(c)
    return _public(c)


@router.put("/{cid}")
def update_connection(cid: int, payload: ConnectionIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    c = _get(db, ws, cid)
    cfg = dict(payload.config or {})
    stored = c.config or {}
    # Preserve the stored key if the client didn't send a fresh one.
    incoming = cfg.get("api_key", "")
    if not incoming or incoming.startswith(MASK):
        cfg["api_key"] = stored.get("api_key", "")
    # Same for masked secret headers — don't let a masked value overwrite the real token.
    hdrs = cfg.get("headers")
    if isinstance(hdrs, dict):
        stored_hdrs = stored.get("headers") or {}
        cfg["headers"] = {k: (stored_hdrs.get(k, v) if isinstance(v, str) and v.startswith(MASK) else v) for k, v in hdrs.items()}
    cfg.pop("has_key", None)
    c.name, c.kind, c.config = payload.name, payload.kind, cfg
    db.commit(); db.refresh(c)
    return _public(c)


@router.delete("/{cid}")
def delete_connection(cid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    c = db.get(Connection, cid)
    if c and c.workspace_id == ws.id:
        db.delete(c); db.commit()
    return {"deleted": True}


class AuthPayload(BaseModel):
    login_path: str = "/api/auth/login"
    method: str = "POST"
    body: dict = {}
    token_path: str = "token"
    header: str = "Authorization"
    scheme: str = "Bearer"


@router.post("/{cid}/authenticate")
def authenticate(cid: int, payload: AuthPayload, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Perform a login against the agent's base URL, extract the token, and store it as a
    default header on the connection. Credentials are used transiently — only the token
    (which expires) is saved, never the username/password."""
    c = _get(db, ws, cid)
    if c.kind != "agent":
        raise HTTPException(400, "Not an agent connection")
    base = (c.config or {}).get("base_url")
    if not base:
        raise HTTPException(400, "Connection has no base_url")
    url = base.rstrip("/") + "/" + payload.login_path.lstrip("/")
    _guard_url(url)
    try:
        r = httpx.request(payload.method.upper(), url, json=payload.body or None, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        raise HTTPException(502, f"Login failed: {exc}")
    token = get_path(data, payload.token_path)
    if not token:
        raise HTTPException(400, f"No token found at '{payload.token_path}' in the login response")
    headers = dict((c.config or {}).get("headers") or {})
    headers[payload.header] = f"{payload.scheme} {token}".strip()
    c.config = {**(c.config or {}), "headers": headers}
    db.commit()
    tok = str(token)
    return {"ok": True, "header": payload.header, "token": (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else "••••"}


DEFAULT_BASE = {"openai": "https://api.openai.com/v1", "openai-responses": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com/v1"}


@router.post("/{cid}/test")
def test_connection(cid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Live reachability/auth check so onboarding can confirm a connection works before use.
    llm → list models · mcp → list tools · agent → GET the base URL."""
    c = _get(db, ws, cid)
    cfg = c.config or {}
    try:
        if c.kind == "mcp":
            if not cfg.get("url") and not cfg.get("command"):
                return {"ok": False, "detail": "No server URL or command set"}
            tools = _mcp_from_cfg(cfg).list_tools()
            return {"ok": True, "detail": f"{len(tools)} tool{'s' if len(tools) != 1 else ''} discovered"}
        if c.kind == "llm":
            provider = cfg.get("provider", "openai")
            if provider == "mock":
                return {"ok": True, "detail": "Demo agent ready — no key needed"}
            base = (cfg.get("base_url") or DEFAULT_BASE.get(provider, "")).rstrip("/")
            key = cfg.get("api_key") or ""
            if not key:
                return {"ok": False, "detail": "No API key set"}
            if not base:
                return {"ok": False, "detail": "No base URL set"}
            _guard_url(base)
            if provider == "anthropic":
                headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            else:
                headers = {"Authorization": f"Bearer {key}"}
            r = httpx.get(base + "/models", headers=headers, timeout=15)
            if r.status_code == 200:
                n = len(((r.json() or {}).get("data")) or [])
                return {"ok": True, "detail": f"Authenticated — {n} models available" if n else "Authenticated ✓"}
            if r.status_code in (401, 403):
                return {"ok": False, "detail": "Key rejected (401/403) — check the API key"}
            return {"ok": False, "detail": f"Provider returned {r.status_code}"}
        if c.kind == "a2a":
            base = (cfg.get("base_url") or "").rstrip("/")
            if not base:
                return {"ok": False, "detail": "No base URL set"}
            _guard_url(base)
            from ..services.providers.a2a_client import fetch_card
            card = fetch_card(base, headers=cfg.get("headers"))
            return {"ok": True, "detail": f"Agent card: {card.get('name')} (A2A {card.get('_version')})"}
        # agent
        base = (cfg.get("base_url") or "").rstrip("/")
        if not base:
            return {"ok": False, "detail": "No base URL set"}
        _guard_url(base)
        r = httpx.get(base, headers=cfg.get("headers") or None, timeout=15)
        return {"ok": r.status_code < 500, "detail": f"Reachable — HTTP {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "detail": f"Unreachable: {str(exc)[:120]}"}


def _mcp_from_cfg(cfg: dict) -> MCPSession:
    """Build an MCP session (stdio | http, spec, oauth) from a connection config."""
    if cfg.get("command"):
        return MCPSession(command=cfg["command"], args=cfg.get("args"), env=cfg.get("env"),
                          spec=cfg.get("spec", "auto"))
    _guard_url(cfg.get("url") or "")
    return MCPSession(cfg.get("url"), headers=cfg.get("headers"),
                      spec=cfg.get("spec", "auto"), oauth=cfg.get("oauth"))


@router.get("/{cid}/agent-card")
def agent_card(cid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Fetch + validate an A2A connection's agent card (for the request form / discovery)."""
    c = _get(db, ws, cid)
    if c.kind != "a2a":
        raise HTTPException(400, "Not an A2A connection")
    base = (c.config or {}).get("base_url")
    if not base:
        raise HTTPException(400, "A2A connection has no base_url")
    _guard_url(base)
    try:
        from ..services.providers.a2a_client import fetch_card
        return {"card": fetch_card(base, headers=(c.config or {}).get("headers"))}
    except Exception as exc:
        raise HTTPException(502, f"A2A error: {exc}")


@router.get("/{cid}/tools")
def list_tools(cid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Discover the tools exposed by an MCP connection (for the tool request form)."""
    c = _get(db, ws, cid)
    if c.kind != "mcp":
        raise HTTPException(400, "Not an MCP connection")
    cfg = c.config or {}
    if not cfg.get("url") and not cfg.get("command"):
        raise HTTPException(400, "MCP connection has no url or command")
    try:
        return {"tools": _mcp_from_cfg(cfg).list_tools()}
    except Exception as exc:
        raise HTTPException(502, f"MCP error: {exc}")
