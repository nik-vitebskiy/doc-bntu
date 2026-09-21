"""Add mandatory password rotation for managed users."""

import sqlalchemy as sa
from alembic import op


revision = "20260921_07"
down_revision = "20260918_06"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "app_user",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Preserve audit authors and existing data, but force known development
    # accounts to replace their temporary password on the next login.
    op.execute(
        "UPDATE app_user SET must_change_password = true "
        "WHERE username IN ('admin', 'head')"
    )


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
