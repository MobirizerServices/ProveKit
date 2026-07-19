"""users.is_superuser + workspaces.retention/redact_pii

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-19 04:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retention', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('redact_pii', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_column('redact_pii')
        batch_op.drop_column('retention')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_superuser')
