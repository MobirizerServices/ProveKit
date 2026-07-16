"""Observability: request IDs, structured JSON logs (hosted), optional Sentry, /healthz.

Logs never include prompt/response bodies or secrets — only run lifecycle metadata.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .database import SessionLocal

request_id: ContextVar[str] = ContextVar("request_id", default="-")


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name,
                   "msg": record.getMessage(), "request_id": request_id.get()}
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging() -> None:
    s = get_settings()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if s.hosted:  # machine-parseable logs in production
        for h in root.handlers:
            h.setFormatter(_JSONFormatter())


def init_sentry() -> None:
    dsn = get_settings().sentry_dsn
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)
        logging.getLogger("agentman").info("sentry enabled")
    except ImportError:
        logging.getLogger("agentman").warning("SENTRY_DSN set but sentry-sdk not installed")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign/propagate X-Request-ID and bind it to logs for the duration of the request."""
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized request bodies (declared Content-Length) with 413."""
    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > get_settings().max_body_bytes:
            from starlette.responses import JSONResponse as _JR
            return _JR({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)


def healthz() -> JSONResponse:
    """Liveness+readiness: DB reachable, and Redis if configured."""
    checks = {"db": False, "redis": None}
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["db"] = True
    except Exception:
        pass
    if get_settings().redis_url:
        checks["redis"] = False
        try:
            from .services.runstore import _store
            _store()._r.ping()
            checks["redis"] = True
        except Exception:
            pass
    ok = checks["db"] and (checks["redis"] is not False)
    return JSONResponse({"ok": ok, "checks": checks}, status_code=200 if ok else 503)
