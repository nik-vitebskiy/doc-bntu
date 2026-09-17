"""Make applications registrable after receipt and signing."""
from alembic import op

revision = "20260917_03"
down_revision = "20260916_02"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE application ALTER COLUMN number DROP NOT NULL")
    op.execute("ALTER TABLE application ALTER COLUMN signed_date DROP NOT NULL")
    op.execute("ALTER TABLE application ADD COLUMN IF NOT EXISTS received_date date")
    op.execute("UPDATE application SET received_date = COALESCE(signed_date, CURRENT_DATE) WHERE received_date IS NULL")
    op.execute("ALTER TABLE application ALTER COLUMN received_date SET NOT NULL")
    op.execute("ALTER TABLE application DROP CONSTRAINT IF EXISTS uq_application_number")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_application_number_present ON application(organization_id, number) WHERE number IS NOT NULL")


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
