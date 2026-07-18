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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers on every response; HSTS only in hosted (TLS) mode."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if get_settings().hosted:
            response.headers.setdefault("Strict-Transport-Security",
                                        "max-age=31536000; includeSubDomains")
        return response


class BodySizeLimitMiddleware:
    """Reject oversized request bodies with 413. Pure ASGI so the cap holds for chunked /
    Content-Length-less requests too: the body is buffered up to the limit and then replayed
    to the app (this API takes small JSON bodies, so buffering is cheap)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        max_bytes = get_settings().max_body_bytes
        headers = dict(scope.get("headers") or [])
        cl = headers.get(b"content-length")
        if cl is not None and cl.isdigit() and int(cl) > max_bytes:
            return await self._reject(send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                # The client vanished mid-upload. Returning bare would satisfy a pure-ASGI
                # parent, but this runs inside BaseHTTPMiddleware (RequestID/SecurityHeaders),
                # whose call_next raises "No response returned." if nothing is sent — turning
                # every cancelled upload into a 500 + Sentry event. Nobody reads this response.
                return await self._respond(send, 499, "Client disconnected")
            body.extend(message.get("body", b""))
            if len(body) > max_bytes:
                return await self._reject(send)
            if not message.get("more_body", False):
                break
        buffered = bytes(body)
        done = False

        async def replay():
            nonlocal done
            if not done:
                done = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            # Delegate later reads to the real channel so a StreamingResponse's disconnect
            # listener gets genuine http.disconnect events (returning a fake one truncates SSE).
            return await receive()

        await self.app(scope, replay, send)

    @classmethod
    async def _reject(cls, send):
        return await cls._respond(send, 413, "Request body too large")

    @staticmethod
    async def _respond(send, status: int, detail: str):
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


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
