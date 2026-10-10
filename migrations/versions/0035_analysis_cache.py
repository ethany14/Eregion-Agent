"""Persist validated analyses and pack timing summaries."""
from alembic import op
import sqlalchemy as sa
revision = '0035_analysis_cache'
down_revision = '0034_career_job_alerts'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('analysis_cache',
        sa.Column('cache_key', sa.String(64), primary_key=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('last_used_at', sa.String(40), nullable=False))
    op.create_index('ix_analysis_cache_last_used_at', 'analysis_cache', ['last_used_at'])
    op.add_column('application_packs', sa.Column('perf_summary_json', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('application_packs', 'perf_summary_json')
    op.drop_index('ix_analysis_cache_last_used_at', table_name='analysis_cache')
    op.drop_table('analysis_cache')
