"""Merge the legacy spelling of the marketing faculty into the reference row."""

from alembic import op


revision = "20260922_08"
down_revision = "20260921_07"
branch_labels = None
depends_on = None


LEGACY_NAME = "Маркетинга, менеджмента и предпринимательства"
CANONICAL_NAME = "Маркетинга, менеджмента, предпринимательства"


def upgrade():
    # Keep current business links while joining the two spellings into the
    # official reference row. ON CONFLICT protects contracts already linked to
    # both variants.
    op.execute(
        f"""
        INSERT INTO contract_faculty(contract_id, faculty_id)
        SELECT link.contract_id, canonical.id
        FROM contract_faculty AS link
        JOIN faculty AS legacy ON legacy.id = link.faculty_id
        JOIN faculty AS canonical ON canonical.name = '{CANONICAL_NAME}'
        WHERE legacy.name = '{LEGACY_NAME}'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO application_faculty(application_id, faculty_id)
        SELECT link.application_id, canonical.id
        FROM application_faculty AS link
        JOIN faculty AS legacy ON legacy.id = link.faculty_id
        JOIN faculty AS canonical ON canonical.name = '{CANONICAL_NAME}'
        WHERE legacy.name = '{LEGACY_NAME}'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        f"""
        DELETE FROM contract_faculty
        WHERE faculty_id IN (SELECT id FROM faculty WHERE name = '{LEGACY_NAME}')
        """
    )
    op.execute(
        f"""
        DELETE FROM application_faculty
        WHERE faculty_id IN (SELECT id FROM faculty WHERE name = '{LEGACY_NAME}')
        """
    )
    op.execute(
        f"""
        UPDATE specialty
        SET faculty = replace(faculty, '{LEGACY_NAME}', '{CANONICAL_NAME}')
        WHERE faculty LIKE '%{LEGACY_NAME}%'
        """
    )
    op.execute(f"DELETE FROM faculty WHERE name = '{LEGACY_NAME}'")


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
