"""scheduled bulk export (#93)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""
import sqlalchemy as sa
from alembic import op

revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'export_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=True),
        sa.Column('cadence', sa.String(length=16), nullable=True),
        sa.Column('destination_url', sa.String(length=500), nullable=True),
        sa.Column('cursor', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(length=16), nullable=True),
        sa.Column('last_error', sa.String(length=300), nullable=True),
        sa.Column('last_rows', sa.Integer(), nullable=True),
        sa.Column('claimed_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_export_schedules_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_export_schedules')),
    )
    with op.batch_alter_table('export_schedules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_export_schedules_workspace_id'), ['workspace_id'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('export_schedules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_export_schedules_workspace_id'))
    op.drop_table('export_schedules')
