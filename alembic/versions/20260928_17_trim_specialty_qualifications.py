"""Trim qualification values in the specialty directory."""

from alembic import op


revision = "20260928_17"
down_revision = "20260925_16"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE specialty "
        "SET qualification = NULLIF(BTRIM(qualification), '') "
        "WHERE qualification IS NOT NULL"
    )


def downgrade():
    # Whitespace removed by normalization cannot be reconstructed.
    pass
