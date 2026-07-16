"""Public runtime — invoke a deployed flow by slug with an API key. No session auth.

POST /v1/d/{slug}          → JSON {output, status, run_id, duration_ms}
POST /v1/d/{slug}?stream=1 → SSE passthrough of the flow's node/delta events

This executes user-defined outbound calls, so it depends on the P0 safeguards
(credential-override block, SSRF guard, secret masking) already in place.
"""
import json
import time

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..database import SessionLocal
from ..models import Deployment, Run
from ..services import deploy
from ..services.limits import _window
from ..config import get_settings

router = APIRouter(prefix="/v1/d", tags=["runtime"])


def _resolve(session, slug: str, api_key: str | None) -> Deployment:
    d = (session.query(Deployment)
         .filter(Deployment.slug == slug, Deployment.active.is_(True))
         .order_by(Deployment.version.desc()).first())
    if not d:
        # Distinguish "never existed / deactivated" without leaking which.
        any_row = session.query(Deployment).filter(Deployment.slug == slug).first()
        raise HTTPException(410 if any_row else 404, "Deployment not available")
    if not api_key or not deploy.verify_key(api_key, d.api_key_hash):
        raise HTTPException(403, "Invalid API key")
    return d


def _rate_ok(deployment_id: int) -> bool:
    limit = get_settings().rate_limit_per_min
    if limit <= 0:
        return True
    key = f"rl:dep:{deployment_id}:{int(time.time()) // 60}"
    return _window().hit(key, 60) <= limit


@router.post("/{slug}")
async def invoke(slug: str, request: Request, stream: bool = False,
                 x_api_key: str | None = Header(default=None)):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    session = SessionLocal()
    try:
        d = _resolve(session, slug, x_api_key)
        if not _rate_ok(d.id):
            raise HTTPException(429, "Rate limit exceeded")
        snapshot, ws_id, dep_id = d.snapshot, d.workspace_id, d.id
    except HTTPException:
        session.close()
        raise

    if stream:
        def gen():
            try:
                for ev in deploy.run_snapshot(session, snapshot, body, ws_id):
                    yield f"data: {json.dumps(ev)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                session.close()
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    try:
        t0 = time.monotonic()
        events = list(deploy.run_snapshot(session, snapshot, body, ws_id))
        result = deploy.collect_output(events)
        dur = round((time.monotonic() - t0) * 1000)
        session.add(Run(workspace_id=ws_id, deployment_id=dep_id, type="deployment",
                        label=f"deploy {slug}", request={"input": body},
                        result={"output": result["output"]}, status=result["status"],
                        duration_ms=dur, error=result["error"]))
        session.commit()
        return {"output": result["output"], "status": result["status"],
                "run_id": result["run_id"], "duration_ms": dur}
    finally:
        session.close()
