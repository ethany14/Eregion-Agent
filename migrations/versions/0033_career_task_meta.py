"""Conversation organisation: custom titles, pins, groups, archive and a 30-day trash."""
from alembic import op
import sqlalchemy as sa

revision = '0033_career_task_meta'
down_revision = '0032_career_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('career_task_groups',sa.Column('group_id',sa.String(40),primary_key=True),
        sa.Column('name',sa.String(80),nullable=False),sa.Column('position',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.String(40),nullable=False))
    with op.batch_alter_table('career_tasks') as batch:
        batch.add_column(sa.Column('title',sa.String(120),nullable=True))
        batch.add_column(sa.Column('group_id',sa.String(40),nullable=True))
        batch.add_column(sa.Column('pinned_at',sa.String(40),nullable=True))
        batch.add_column(sa.Column('archived_at',sa.String(40),nullable=True))
        batch.add_column(sa.Column('trashed_at',sa.String(40),nullable=True))
        batch.create_index('ix_career_tasks_trashed_at',['trashed_at'])


def downgrade():
    with op.batch_alter_table('career_tasks') as batch:
        batch.drop_index('ix_career_tasks_trashed_at')
        for column in ('trashed_at','archived_at','pinned_at','group_id','title'):
            batch.drop_column(column)
    op.drop_table('career_task_groups')
