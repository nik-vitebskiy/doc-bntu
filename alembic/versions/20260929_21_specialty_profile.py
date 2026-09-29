"""Add an optional profile to the specialty directory."""

import sqlalchemy as sa
from alembic import op


revision = "20260929_21"
down_revision = "20260929_20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("specialty", sa.Column("profile", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("specialty", "profile")
