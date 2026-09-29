"""Use an optional validity date instead of application receipt date."""

import sqlalchemy as sa
from alembic import op


revision = "20260929_19"
down_revision = "20260928_18"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("application", sa.Column("date_end", sa.Date(), nullable=True))
    op.alter_column("application", "received_date", existing_type=sa.Date(), nullable=True)


def downgrade():
    op.execute("UPDATE application SET received_date = COALESCE(received_date, signed_date, CURRENT_DATE)")
    op.alter_column("application", "received_date", existing_type=sa.Date(), nullable=False)
    op.drop_column("application", "date_end")
