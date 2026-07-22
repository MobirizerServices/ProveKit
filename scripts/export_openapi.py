#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to a file so consumers can diff it and generate clients.

The running app already serves `/openapi.json`, but that only helps someone who has an
instance up. Committing the spec makes it reviewable in a pull request: a route that changes
shape shows up as a schema diff instead of as a broken client three weeks later.

    python scripts/export_openapi.py                # write docs/openapi.json
    python scripts/export_openapi.py --check        # exit 1 if the file is stale
    python scripts/export_openapi.py --out -        # write to stdout

Import-only: it builds the schema from `provekit.main:app` without starting the server, so
no database, Redis, or secrets are needed (`init_db` runs in the lifespan, not at import).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "openapi.json"


def _load_app():
    """Import the app with the backend package on the path.

    Force a SQLite URL so importing `provekit.main` can never bind a real database — the
    engine is constructed at import time even though it is not connected to until startup.
    """
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("DATABASE_URL", "sqlite:///./openapi-export.db")
    from provekit.main import app  # deliberately late: needs the sys.path/env setup above
    return app


def build_schema() -> dict:
    app = _load_app()
    # Reset the cache so repeated calls in one process (tests) re-derive the schema.
    app.openapi_schema = None
    return app.openapi()


def render(schema: dict) -> str:
    """Serialize deterministically.

    `sort_keys` matters: FastAPI derives `components.schemas` from a dict whose insertion
    order follows import order, so without it a harmless refactor produces a large,
    meaningless diff and `--check` fails for the wrong reason.
    """
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output file, or '-' for stdout (default: docs/openapi.json)")
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the file differs from the current app")
    args = ap.parse_args(argv)

    text = render(build_schema())

    if args.out == "-":
        sys.stdout.write(text)
        return 0

    out = Path(args.out)
    if args.check:
        if not out.exists():
            print(f"{out} is missing — run: python scripts/export_openapi.py", file=sys.stderr)
            return 1
        if out.read_text(encoding="utf-8") != text:
            print(f"{out} is stale — run: python scripts/export_openapi.py", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    changed = not out.exists() or out.read_text(encoding="utf-8") != text
    out.write_text(text, encoding="utf-8")
    paths = len(json.loads(text).get("paths", {}))
    print(f"{'wrote' if changed else 'unchanged'} {out} ({paths} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
