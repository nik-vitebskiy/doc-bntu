"""Add email to user accounts.

Existing users intentionally keep NULL: after deployment they are asked once
to provide an address before continuing work.
"""

import sqlalchemy as sa
from alembic import op


revision = "20260930_23"
down_revision = "20260929_22"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_user", sa.Column("email", sa.String(length=320), nullable=True))
    op.create_unique_constraint("uq_app_user_email", "app_user", ["email"])


def downgrade():
    op.drop_constraint("uq_app_user_email", "app_user", type_="unique")
    op.drop_column("app_user", "email")
