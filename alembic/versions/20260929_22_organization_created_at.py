"""Track creation time for organization statistics."""

import sqlalchemy as sa
from alembic import op


revision = "20260929_22"
down_revision = "20260929_21"
branch_labels = None
depends_on = None


def upgrade():
    # Existing organizations have no reliable creation timestamp. Keep them
    # NULL so the "last 30 days" delta does not report migrated data as new.
    op.add_column("organization", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("organization", "created_at", server_default=sa.text("now()"))


def downgrade():
    op.drop_column("organization", "created_at")
