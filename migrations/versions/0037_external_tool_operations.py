"""Durable spend records for external paid tools (Treg), separate from model usage."""
from alembic import op
import sqlalchemy as sa

revision = '0037_external_tool_operations'
down_revision = '0036_provider_usage'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('external_tool_operations',
        sa.Column('operation_id', sa.String(40), primary_key=True),
        sa.Column('scope', sa.String(80), nullable=False),
        sa.Column('task_id', sa.String(40)),
        sa.Column('run_id', sa.String(40)),
        sa.Column('revision', sa.String(40)),
        sa.Column('endpoint', sa.String(80), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(80), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reserved_micro', sa.Integer(), nullable=False),
        sa.Column('charged_micro', sa.Integer()),
        sa.Column('original_cost_micro', sa.Integer()),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('billing_day', sa.String(10), nullable=False),
        sa.Column('call_id', sa.String(80)),
        sa.Column('claim_owner', sa.String(40)),
        sa.Column('claim_expires', sa.String(40)),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=False))
    for name in ('scope', 'task_id', 'status', 'billing_day'):
        op.create_index('ix_external_tool_operations_' + name, 'external_tool_operations', [name])


def downgrade():
    op.drop_table('external_tool_operations')
