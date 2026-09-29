"""Merge the accidentally concatenated mining faculty duplicate."""

from alembic import op


revision = "20260929_20"
down_revision = "20260929_19"
branch_labels = None
depends_on = None


CORRECT_NAME = "Горного дела и инженерной экологии"
DUPLICATED_NAME = CORRECT_NAME + CORRECT_NAME


def upgrade():
    op.execute(f"""
        DO $$
        DECLARE source_id bigint; target_id bigint;
        BEGIN
            SELECT id INTO source_id FROM faculty WHERE name = '{DUPLICATED_NAME}';
            IF source_id IS NULL THEN
                RETURN;
            END IF;

            SELECT id INTO target_id FROM faculty WHERE name = '{CORRECT_NAME}';
            IF target_id IS NULL THEN
                UPDATE faculty SET name = '{CORRECT_NAME}' WHERE id = source_id;
                RETURN;
            END IF;

            INSERT INTO contract_faculty(contract_id, faculty_id)
            SELECT contract_id, target_id FROM contract_faculty WHERE faculty_id = source_id
            ON CONFLICT DO NOTHING;
            DELETE FROM contract_faculty WHERE faculty_id = source_id;

            INSERT INTO application_faculty(application_id, faculty_id)
            SELECT application_id, target_id FROM application_faculty WHERE faculty_id = source_id
            ON CONFLICT DO NOTHING;
            DELETE FROM application_faculty WHERE faculty_id = source_id;

            UPDATE order_item SET faculty_id = target_id WHERE faculty_id = source_id;
            DELETE FROM faculty WHERE id = source_id;
        END $$;
    """)


def downgrade():
    # The bad row was accidental duplicate reference data and must not return.
    pass
