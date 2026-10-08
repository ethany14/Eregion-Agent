"""Persist site-specific application attempts and submission uncertainty."""
from alembic import op
import sqlalchemy as sa

revision = "0029_auto_applications"
down_revision = "0028_review_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("auto_applications",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("posting_key", sa.String(512), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("resume_bytes", sa.LargeBinary(), nullable=False))


def downgrade():
    op.drop_table("auto_applications")
