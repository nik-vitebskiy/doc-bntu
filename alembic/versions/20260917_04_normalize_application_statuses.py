"""Align application statuses with the approved production vocabulary."""
from alembic import op


revision = "20260917_04"
down_revision = "20260917_03"
branch_labels = None
depends_on = None


def upgrade():
    # The earlier prototype vocabulary had a separate completed-application
    # state. The approved workflow keeps only "Заявка" and "Закрыт".
    op.execute("UPDATE application SET status = 'Закрыт' WHERE status = 'Закрыта заявка'")
    op.execute("UPDATE application SET status = 'Заявка' WHERE status = 'Активна'")


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
