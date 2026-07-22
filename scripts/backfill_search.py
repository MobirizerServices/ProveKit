#!/usr/bin/env python
"""Populate `runs.search_text` for spans ingested before that column existed.

Migration c5d6e7f8a9b0 adds the column but deliberately does not fill it: rewriting every row
in the largest table in the schema, inside a migration that runs on boot, is an outage on any
instance big enough to care about search performance. Until a row is backfilled,
`services/search.clause()` still matches it through the old JSON scan — correct, just slow.

Run this when convenient. It is resumable (only touches rows where search_text IS NULL),
batched so it never holds a long transaction, and safe to run while the app is serving.

    python scripts/backfill_search.py                  # all workspaces
    python scripts/backfill_search.py --batch 2000
    python scripts/backfill_search.py --workspace 3
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from provekit.database import SessionLocal          # noqa: E402
from provekit.models import Run                     # noqa: E402
from provekit.services import search                # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=int, default=1000, help="rows per transaction")
    ap.add_argument("--workspace", type=int, default=None, help="limit to one workspace id")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="seconds to pause between batches, to stay out of the way of ingest")
    args = ap.parse_args()

    done = 0
    while True:
        db = SessionLocal()
        try:
            q = db.query(Run).filter(Run.search_text.is_(None))
            if args.workspace is not None:
                q = q.filter(Run.workspace_id == args.workspace)
            rows = q.limit(args.batch).all()
            if not rows:
                break
            for r in rows:
                # Built from what is stored, which is already redacted — the same guarantee the
                # ingest path gives. Never re-derive this from anything unmasked.
                r.search_text = search.text_for({
                    "label": r.label, "request": r.request, "result": r.result, "error": r.error})
            db.commit()
            done += len(rows)
            print(f"\rbackfilled {done} spans…", end="", flush=True)
            if len(rows) < args.batch:
                break                      # last partial batch; don't re-query for nothing
        finally:
            db.close()
        if args.sleep:
            time.sleep(args.sleep)

    print(f"\rbackfilled {done} spans — done." if done else "nothing to backfill.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
