"""runs — composite indexes for the hot read paths

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-22 09:30:00.000000

Every index here comes from a predicate that actually appears in the code, not from a guess.
The shapes, and where they run:

  (workspace_id, parent_span_id, id)   trace list, metrics roots, admin counts, dataset lookup
  (workspace_id, created_at)           every windowed metrics query — the widest scan we have
  (workspace_id, status, created_at)   the failures panel
  (workspace_id, session_id)           session grouping

`workspace_id` alone was already indexed, which is why none of these were catastrophic — but
it is also the *least* selective column in a single-tenant-heavy table, so on a busy project
Postgres reads the whole workspace and filters in memory. Leading with it and carrying the
discriminating column is what turns those into index scans.

Deliberately NOT adding a bare `span_id` index, which docs/ROADMAP_100.md #18 called for: no
query filters on span_id alone (uq_run_span already covers workspace+trace+span lookups, and
replay compares span ids in Python after loading a trace). An unused index still costs a write
on every ingested span, which is the hottest write path in the product.
"""
from alembic import op


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


_INDEXES = [
    # Roots are a small fraction of rows, so leading the composite with the parent filter and
    # trailing `id` lets "newest N traces in this project" be an index-only walk backwards
    # rather than a scan of every span the project ever sent.
    ("ix_runs_ws_root", ["workspace_id", "parent_span_id", "id"]),
    ("ix_runs_ws_created", ["workspace_id", "created_at"]),
    ("ix_runs_ws_status_created", ["workspace_id", "status", "created_at"]),
    ("ix_runs_ws_session", ["workspace_id", "session_id"]),
]


def upgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        for name, cols in _INDEXES:
            batch_op.create_index(name, cols)


def downgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        for name, _ in reversed(_INDEXES):
            batch_op.drop_index(name)
