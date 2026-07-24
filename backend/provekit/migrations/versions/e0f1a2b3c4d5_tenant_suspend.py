"""tenant lifecycle: workspace suspension (#82)

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""
import sqlalchemy as sa
from alembic import op

revision = 'e0f1a2b3c4d5'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('suspended_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('suspended_reason', sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_column('suspended_reason')
        batch_op.drop_column('suspended_at')
