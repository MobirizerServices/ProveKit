"""dataset versioning + splits, and experiment reproducibility pins

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-22 15:00:00.000000

Existing rows get version=1, split='' and empty pins rather than a backfill. An experiment
that ran before this existed genuinely has no recorded provenance, and inventing one — say,
stamping it with today's dataset contents — would be worse than the gap: it would assert that
a historical result is reproducible when nobody can know that. dataset_version=0 reads as
"unrecorded", which is the truth.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd6e7f8a9b0c1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=False,
                                      server_default='1'))
    with op.batch_alter_table('dataset_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('split', sa.String(length=16), nullable=False,
                                      server_default=''))
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dataset_version', sa.Integer(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('dataset_fingerprint', sa.String(length=64),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('config', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_column('config')
        batch_op.drop_column('dataset_fingerprint')
        batch_op.drop_column('dataset_version')
    with op.batch_alter_table('dataset_items', schema=None) as batch_op:
        batch_op.drop_column('split')
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_column('version')
