"""Remove the obsolete internal DRAFT default.

Documents enter the system after conclusion, so neither an order revision nor
its file card has a business draft state.  Historical audit rows are immutable
and intentionally remain untouched; the registry has a compatibility display
for the one pre-fix value.
"""

import sqlalchemy as sa
from alembic import op


revision = "20260924_14"
down_revision = "20260923_13"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE orders SET status = 'CURRENT' WHERE status = 'DRAFT'"))
    connection.execute(sa.text("UPDATE document SET status = 'CURRENT' WHERE status = 'DRAFT'"))
    op.alter_column("orders", "status", existing_type=sa.String(30), server_default="CURRENT", nullable=False)
    op.alter_column("document", "status", existing_type=sa.String(30), server_default="CURRENT", nullable=False)


def downgrade():
    op.alter_column("document", "status", existing_type=sa.String(30), server_default="DRAFT", nullable=False)
    op.alter_column("orders", "status", existing_type=sa.String(30), server_default="DRAFT", nullable=False)
