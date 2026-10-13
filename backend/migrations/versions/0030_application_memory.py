"""Confirmed application answers, scoped to the candidate email."""
from alembic import op
import sqlalchemy as sa

revision = "0030_application_memory"
down_revision = "0029_auto_applications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("application_answer_memory",
        sa.Column("memory_id", sa.String(64), primary_key=True),
        sa.Column("owner_key", sa.String(64), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False))
    op.create_index("ix_application_answer_memory_owner_key", "application_answer_memory", ["owner_key"])


def downgrade():
    op.drop_table("application_answer_memory")
