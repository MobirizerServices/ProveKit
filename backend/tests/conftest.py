"""Test env: isolated SQLite db + no example seeds. Must run before `app` imports."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="agentman-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SEED_EXAMPLES"] = "false"
