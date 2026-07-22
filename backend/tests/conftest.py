"""Test env: isolated SQLite db + no example seeds. Must run before `app` imports."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="provekit-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SEED_EXAMPLES"] = "false"
# Keep the ingest spool inside this run's temp dir. Sharing the default (a system temp path)
# would let one run's leftover batches count toward another's backlog and depth assertions.
os.environ["SPOOL_DIR"] = f"{_tmp}/spool"

# Create the schema eagerly so tests using a bare TestClient (no lifespan) still have tables.
from provekit.database import init_db  # noqa: E402
init_db()


def ingest_workspace_id() -> int:
    """The workspace an unauthenticated ingest actually lands in.

    Do not reach for `Workspace.first()`. The local workspace is created lazily on the first
    request, so it doesn't exist at import time — and once other tests in the suite have
    created workspaces, `first()` returns some other tenant. Tests that then set retention or
    redaction on that row pass alone and fail in the suite, having asserted nothing.
    """
    from fastapi.testclient import TestClient

    from provekit.database import SessionLocal
    from provekit.main import app
    from provekit.models import Run

    probe = "3e" * 16
    span = {"name": "probe", "traceId": probe, "spanId": "3f" * 8,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1100000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "probe"}}]}
    with TestClient(app) as client:
        client.post("/v1/traces",
                    json={"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.trace_id == probe).first().workspace_id
    finally:
        db.close()
