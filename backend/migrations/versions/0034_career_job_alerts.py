"""Scheduled autonomous searches and recommendation digests."""
from alembic import op
import sqlalchemy as sa

revision='0034_career_job_alerts'
down_revision='0033_career_task_meta'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('career_job_alerts',sa.Column('alert_id',sa.String(40),primary_key=True),
        sa.Column('request_key',sa.String(160),unique=True,nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('config_json',sa.Text(),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),
        sa.Column('next_run_at',sa.String(40),nullable=False),sa.Column('created_at',sa.String(40),nullable=False),
        sa.Column('updated_at',sa.String(40),nullable=False))
    op.create_index('ix_career_job_alerts_next_run_at','career_job_alerts',['next_run_at'])
    op.create_table('career_alert_runs',sa.Column('run_id',sa.String(40),primary_key=True),
        sa.Column('alert_id',sa.String(40),nullable=False),sa.Column('slot_key',sa.String(180),unique=True,nullable=False),
        sa.Column('config_json',sa.Text(),nullable=False),sa.Column('task_id',sa.String(40)),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('scheduled_for',sa.String(40),nullable=False),
        sa.Column('created_at',sa.String(40),nullable=False),sa.Column('finished_at',sa.String(40)),
        sa.Column('read_at',sa.String(40)),sa.Column('summary',sa.Text()))
    op.create_index('ix_career_alert_runs_alert_id','career_alert_runs',['alert_id'])
    op.create_table('career_recommendations',sa.Column('recommendation_id',sa.String(40),primary_key=True),
        sa.Column('run_id',sa.String(40),nullable=False),sa.Column('job_key',sa.String(250),unique=True,nullable=False),
        sa.Column('payload_json',sa.Text(),nullable=False),sa.Column('created_at',sa.String(40),nullable=False))
    op.create_index('ix_career_recommendations_run_id','career_recommendations',['run_id'])


def downgrade():
    for table in ('career_recommendations','career_alert_runs','career_job_alerts'):op.drop_table(table)
