"""Test env: isolated SQLite db + no example seeds. Must run before `app` imports."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="provekit-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SEED_EXAMPLES"] = "false"

# Create the schema eagerly so tests using a bare TestClient (no lifespan) still have tables.
from provekit.database import init_db  # noqa: E402
init_db()
