"""Remove the legacy single-faculty column from contracts.

The association table ``contract_faculty`` is now the only source of truth.
"""

from alembic import op


revision = "20260916_02"
down_revision = "20260916_01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM contract c
                WHERE NOT EXISTS (
                    SELECT 1 FROM contract_faculty cf WHERE cf.contract_id = c.id
                )
            ) THEN
                RAISE EXCEPTION 'Cannot remove contract.faculty_id: contracts without faculty links exist';
            END IF;
        END $$;
    """)
    # Historical Excel data contains the same contract number under different
    # faculties.  Do not reject it here: consolidation is a separate,
    # reviewable data-cleanup operation.
    op.execute("ALTER TABLE contract DROP CONSTRAINT IF EXISTS uq_contract_number")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contract_organization_number ON contract(organization_id, number)")
    op.execute("ALTER TABLE contract DROP COLUMN IF EXISTS faculty_id")
    op.execute("UPDATE contract SET status = 'Активен' WHERE status = 'ACTIVE'")
    op.execute("UPDATE contract SET status = 'Закрыт' WHERE status = 'CLOSED'")


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
