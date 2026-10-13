"""Durable local applicant profile and original resume for new applications."""
from alembic import op
import sqlalchemy as sa

revision = "0031_saved_candidate"
down_revision = "0030_application_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("saved_application_candidate",
        sa.Column("slot",sa.String(40),primary_key=True),
        sa.Column("profile_json",sa.Text(),nullable=False),
        sa.Column("resume_bytes",sa.LargeBinary(),nullable=True),
        sa.Column("resume_name",sa.String(250),nullable=False),
        sa.Column("extracted",sa.Integer(),nullable=False),
        sa.Column("updated_at",sa.String(50),nullable=False))


def downgrade():
    op.drop_table("saved_application_candidate")
