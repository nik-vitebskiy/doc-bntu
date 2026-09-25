"""Remove obsolete BNTU requisites after document generation was retired."""

import sqlalchemy as sa
from alembic import op


revision = "20260925_16"
down_revision = "20260925_15"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        "DELETE FROM app_setting WHERE key LIKE 'bntu.%'"
    ))


def downgrade():
    raise NotImplementedError("Obsolete requisites are not restored.")
