"""span notes: replies, @mentions and resolve (#65)

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""
import sqlalchemy as sa
from alembic import op

revision = 'd9e0f1a2b3c4'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('span_notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('mentions', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('resolved_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('resolved_by', sa.String(length=120), nullable=True))
        batch_op.create_index(batch_op.f('ix_span_notes_parent_id'), ['parent_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_span_notes_parent_id_span_notes'),
                                    'span_notes', ['parent_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('span_notes', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_span_notes_parent_id_span_notes'),
                                 type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_span_notes_parent_id'))
        batch_op.drop_column('resolved_by')
        batch_op.drop_column('resolved_at')
        batch_op.drop_column('mentions')
        batch_op.drop_column('parent_id')
