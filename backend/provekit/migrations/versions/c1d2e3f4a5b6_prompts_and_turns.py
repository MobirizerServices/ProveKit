"""prompt labels + traffic split, and multi-turn dataset items

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-07-22 23:30:00.000000

Every existing row keeps its exact meaning: label='' and traffic=0 means a saved prompt serves
nobody until someone opts it in, and turns=[] means a dataset item is still the single-turn
{input, expected} row it has always been. A migration that silently started serving prompts or
reinterpreting datasets would change what saved experiments measured.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b0c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('prompts', schema=None) as b:
        b.add_column(sa.Column('label', sa.String(length=64), nullable=False, server_default=''))
        b.add_column(sa.Column('traffic', sa.Float(), nullable=False, server_default='0'))
        b.create_index(b.f('ix_prompts_label'), ['label'])
    with op.batch_alter_table('dataset_items', schema=None) as b:
        b.add_column(sa.Column('turns', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('dataset_items', schema=None) as b:
        b.drop_column('turns')
    with op.batch_alter_table('prompts', schema=None) as b:
        b.drop_index(b.f('ix_prompts_label'))
        b.drop_column('traffic')
        b.drop_column('label')
