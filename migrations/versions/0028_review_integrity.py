"""Persist analysis sources, regeneration instructions and model budgets."""
from alembic import op
import sqlalchemy as sa

revision = "0028_review_integrity"
down_revision = "0027_session_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("application_resume_sources",
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("application_artifacts.artifact_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("resume_id", sa.String(36), nullable=True),
        sa.Column("resume_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False))
    op.add_column("application_pack_items", sa.Column("regeneration_feedback", sa.Text(), nullable=True))
    op.add_column("agent_plans", sa.Column("usage_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("agent_plans", "usage_json")
    op.drop_column("application_pack_items", "regeneration_feedback")
    op.drop_table("application_resume_sources")
