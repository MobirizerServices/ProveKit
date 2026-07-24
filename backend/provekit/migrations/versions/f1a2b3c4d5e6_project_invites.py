"""pending project invites (#73)

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""
import sqlalchemy as sa
from alembic import op

revision = 'f1a2b3c4d5e6'
down_revision = 'e0f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=True),
        sa.Column('invited_by_email', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_project_invites_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_invites')),
    )
    with op.batch_alter_table('project_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_project_invites_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_project_invites_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index('ix_project_invites_ws_email', ['workspace_id', 'email'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('project_invites', schema=None) as batch_op:
        batch_op.drop_index('ix_project_invites_ws_email')
        batch_op.drop_index(batch_op.f('ix_project_invites_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_project_invites_email'))
    op.drop_table('project_invites')
