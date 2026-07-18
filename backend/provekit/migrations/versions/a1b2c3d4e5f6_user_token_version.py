"""user token_version

Revision ID: a1b2c3d4e5f6
Revises: 323eb73d463c
Create Date: 2026-07-17 06:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '323eb73d463c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        # server_default="0" so the NOT NULL column populates on existing rows; all current
        # sessions carry v=0 (or no v, read as 0) and stay valid until the next reset.
        batch_op.add_column(sa.Column('token_version', sa.Integer(), nullable=False,
                                      server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('token_version')
