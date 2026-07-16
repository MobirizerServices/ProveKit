"""Connections (providers): llm | mcp | agent. Secrets are masked in responses and
preserved on update when the client sends a masked/empty key."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Connection, iso_utc
from ..services.assertions import get_path
from ..services.masking import MASK, mask_headers, mask_value
from ..services.netguard import BlockedURL, guard_url
from ..services.providers.mcp_client import MCPSession


def _guard_url(url: str) -> None:
    """Shared SSRF guard (services.netguard), surfaced as a 400 for router callers."""
    try:
        guard_url(url)
    except BlockedURL as exc:
        raise HTTPException(400, str(exc))


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
def list_connections(db: Session = Depends(get_db)):
    return [_public(c) for c in db.query(Connection).order_by(Connection.id).all()]


@router.post("")
def create_connection(payload: ConnectionIn, db: Session = Depends(get_db)):
    c = Connection(name=payload.name, kind=payload.kind, config=payload.config or {})
    db.add(c); db.commit(); db.refresh(c)
    return _public(c)


@router.put("/{cid}")
def update_connection(cid: int, payload: ConnectionIn, db: Session = Depends(get_db)):
    c = db.get(Connection, cid)
    if not c:
        raise HTTPException(404, "Connection not found")
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
def delete_connection(cid: int, db: Session = Depends(get_db)):
    c = db.get(Connection, cid)
    if c:
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
def authenticate(cid: int, payload: AuthPayload, db: Session = Depends(get_db)):
    """Perform a login against the agent's base URL, extract the token, and store it as a
    default header on the connection. Credentials are used transiently — only the token
    (which expires) is saved, never the username/password."""
    c = db.get(Connection, cid)
    if not c or c.kind != "agent":
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
def test_connection(cid: int, db: Session = Depends(get_db)):
    """Live reachability/auth check so onboarding can confirm a connection works before use.
    llm → list models · mcp → list tools · agent → GET the base URL."""
    c = db.get(Connection, cid)
    if not c:
        raise HTTPException(404, "Connection not found")
    cfg = c.config or {}
    try:
        if c.kind == "mcp":
            url = cfg.get("url")
            if not url:
                return {"ok": False, "detail": "No server URL set"}
            _guard_url(url)
            tools = MCPSession(url, headers=cfg.get("headers")).list_tools()
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
        # agent
        base = (cfg.get("base_url") or "").rstrip("/")
        if not base:
            return {"ok": False, "detail": "No base URL set"}
        _guard_url(base)
        r = httpx.get(base, headers=cfg.get("headers") or None, timeout=15)
        return {"ok": r.status_code < 500, "detail": f"Reachable — HTTP {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "detail": f"Unreachable: {str(exc)[:120]}"}


@router.get("/{cid}/tools")
def list_tools(cid: int, db: Session = Depends(get_db)):
    """Discover the tools exposed by an MCP connection (for the tool request form)."""
    c = db.get(Connection, cid)
    if not c or c.kind != "mcp":
        raise HTTPException(400, "Not an MCP connection")
    url = (c.config or {}).get("url")
    if not url:
        raise HTTPException(400, "MCP connection has no url")
    try:
        return {"tools": MCPSession(url, headers=(c.config or {}).get("headers")).list_tools()}
    except Exception as exc:
        raise HTTPException(502, f"MCP error: {exc}")
