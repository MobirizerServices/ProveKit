"""api keys

Revision ID: b2d4f6a8c1e3
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d4f6a8c1e3'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Named constraints match Base.metadata's naming convention so SQLite batch alters can
    # find them later.
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('prefix', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name='fk_api_keys_workspace_id_workspaces'),
        sa.PrimaryKeyConstraint('id', name='pk_api_keys'),
    )
    op.create_index('ix_api_keys_workspace_id', 'api_keys', ['workspace_id'], unique=False)
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_api_keys_key_hash', table_name='api_keys')
    op.drop_index('ix_api_keys_workspace_id', table_name='api_keys')
    op.drop_table('api_keys')
