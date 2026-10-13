"""Durable provider usage without conversation or application version changes."""
from alembic import op
import sqlalchemy as sa

revision = '0036_provider_usage'
down_revision = '0035_analysis_cache'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('provider_usage',
        sa.Column('call_id', sa.String(40), primary_key=True),
        sa.Column('task_id', sa.String(40)),
        sa.Column('run_id', sa.String(40)),
        sa.Column('request_id', sa.String(40)),
        sa.Column('adopted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=False))
    for name in ('task_id', 'run_id', 'request_id'):
        op.create_index('ix_provider_usage_' + name, 'provider_usage', [name])


def downgrade():
    op.drop_table('provider_usage')
