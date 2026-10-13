"""Unified career conversations over reusable job capabilities."""
from alembic import op
import sqlalchemy as sa

revision = '0032_career_tasks'
down_revision = '0031_saved_candidate'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('career_tasks',sa.Column('task_id',sa.String(40),primary_key=True),
        sa.Column('request_key',sa.String(100),nullable=False,unique=True),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('state_json',sa.Text(),nullable=False))


def downgrade():
    op.drop_table('career_tasks')
