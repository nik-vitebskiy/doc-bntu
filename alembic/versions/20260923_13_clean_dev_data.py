"""Clean development data before the first production deployment.

This migration is the single pre-production exception to audit immutability.
The audit log becomes strictly immutable again as soon as this migration
finishes, and must never be cleaned this way after the system is commissioned.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260923_13"
down_revision = "20260923_12"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()

    # System imports have no employee author.  A nullable foreign key represents
    # that honestly and removes the old hidden `demo` pseudo-account.
    op.alter_column("orders", "created_by", existing_type=sa.BigInteger(), nullable=True)
    connection.execute(sa.text("UPDATE orders SET created_by = NULL WHERE created_by IN (SELECT id FROM app_user WHERE username = 'demo')"))
    connection.execute(sa.text("DELETE FROM app_user WHERE username = 'demo'"))

    # Four MТЗ order rows were manually moved between faculties while testing.
    # A later re-import then recreated their source rows.  Restore the original
    # file assignment on the oldest rows first; the duplicate cleanup below can
    # consequently retain the original IDs referenced by the real import audit.
    connection.execute(sa.text("""
        WITH expected(code, faculty_name) AS (
            VALUES
                ('1-36 01 03 02', 'Машиностроительный'),
                ('1-42 01 01-01 03', 'Механико-технологический'),
                ('1-27 01 01-02', 'Автотракторный'),
                ('1-25 01 07', 'Маркетинга, менеджмента, предпринимательства')
        ), oldest AS (
            SELECT DISTINCT ON (s.code) oi.id, oi.order_id, oi.specialty_id, s.code
              FROM order_item oi
              JOIN orders ord ON ord.id = oi.order_id
              JOIN contract c ON c.id = ord.contract_id
              JOIN organization org ON org.id = c.organization_id
              JOIN specialty s ON s.id = oi.specialty_id
              JOIN expected ON expected.code = s.code
             WHERE org.unp = '100316761'
               AND c.number = 'д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020'
             ORDER BY s.code, oi.id
        )
        DELETE FROM order_item duplicate
         USING oldest, expected, faculty f
         WHERE duplicate.order_id = oldest.order_id
           AND duplicate.specialty_id = oldest.specialty_id
           AND duplicate.id <> oldest.id
           AND expected.code = oldest.code
           AND f.name = expected.faculty_name
           AND duplicate.faculty_id = f.id
    """))
    connection.execute(sa.text("""
        WITH expected(code, faculty_name) AS (
            VALUES
                ('1-36 01 03 02', 'Машиностроительный'),
                ('1-42 01 01-01 03', 'Механико-технологический'),
                ('1-27 01 01-02', 'Автотракторный'),
                ('1-25 01 07', 'Маркетинга, менеджмента, предпринимательства')
        ), oldest AS (
            SELECT DISTINCT ON (s.code) oi.id, expected.faculty_name
              FROM order_item oi
              JOIN orders ord ON ord.id = oi.order_id
              JOIN contract c ON c.id = ord.contract_id
              JOIN organization org ON org.id = c.organization_id
              JOIN specialty s ON s.id = oi.specialty_id
              JOIN expected ON expected.code = s.code
             WHERE org.unp = '100316761'
               AND c.number = 'д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020'
             ORDER BY s.code, oi.id
        )
        UPDATE order_item oi
           SET faculty_id = f.id
          FROM oldest, faculty f
         WHERE oi.id = oldest.id
           AND f.name = oldest.faculty_name
    """))
    connection.execute(sa.text("""
        WITH duplicates AS (
            SELECT oi.id,
                   row_number() OVER (
                       PARTITION BY oi.order_id, oi.faculty_id, oi.specialty_id
                       ORDER BY oi.id
                   ) AS duplicate_number
              FROM order_item oi
              JOIN orders ord ON ord.id = oi.order_id
              JOIN contract c ON c.id = ord.contract_id
              JOIN organization org ON org.id = c.organization_id
             WHERE org.unp = '100316761'
               AND c.number = 'д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020'
        )
        DELETE FROM order_item
         WHERE id IN (SELECT id FROM duplicates WHERE duplicate_number > 1)
    """))

    # Resolve the exact development entities before deleting anything.  Exact
    # names/numbers are intentional: this migration must never guess from broad
    # words such as "test" and risk deleting a real customer document.
    connection.execute(sa.text("""
        CREATE TEMP TABLE demo_test_organizations ON COMMIT DROP AS
        SELECT id FROM organization
         WHERE unp = '000000001'
            OR short_name IN ('ТЕСТ — Организация-заказчик', 'АУДИТ — Тестовая организация')
            OR full_name IN ('Тестовая организация для проверки функций', 'АУДИТ — Тестовая организация')
    """))
    connection.execute(sa.text("""
        CREATE TEMP TABLE demo_test_contracts ON COMMIT DROP AS
        SELECT c.id
          FROM contract c
          JOIN organization org ON org.id = c.organization_id
         WHERE c.organization_id IN (SELECT id FROM demo_test_organizations)
            OR (org.unp = '100316761' AND c.number IN ('З-ТЕСТ-2026/01', 'ТЕСТ-2026/02'))
    """))
    connection.execute(sa.text("""
        CREATE TEMP TABLE demo_test_applications ON COMMIT DROP AS
        SELECT a.id
          FROM application a
          JOIN organization org ON org.id = a.organization_id
         WHERE a.organization_id IN (SELECT id FROM demo_test_organizations)
            OR (org.unp = '100316761' AND a.number = 'З-ТЕСТ-2026/01')
    """))
    connection.execute(sa.text("""
        CREATE TEMP TABLE demo_test_agreements ON COMMIT DROP AS
        SELECT id FROM additional_agreement
         WHERE contract_id IN (SELECT id FROM demo_test_contracts)
            OR number IN ('З-ТЕСТ-2026/01', 'ТЕСТ-ДС-2026/01')
    """))
    connection.execute(sa.text("""
        CREATE TEMP TABLE demo_test_orders ON COMMIT DROP AS
        SELECT id FROM orders
         WHERE organization_id IN (SELECT id FROM demo_test_organizations)
            OR contract_id IN (SELECT id FROM demo_test_contracts)
            OR application_id IN (SELECT id FROM demo_test_applications)
            OR additional_agreement_id IN (SELECT id FROM demo_test_agreements)
    """))
    connection.execute(sa.text("""
        CREATE TEMP TABLE demo_test_documents ON COMMIT DROP AS
        SELECT id FROM document
         WHERE organization_id IN (SELECT id FROM demo_test_organizations)
            OR contract_id IN (SELECT id FROM demo_test_contracts)
            OR application_id IN (SELECT id FROM demo_test_applications)
            OR additional_agreement_id IN (SELECT id FROM demo_test_agreements)
    """))

    connection.execute(sa.text("DELETE FROM contract_redirect WHERE old_contract_id IN (SELECT id FROM demo_test_contracts) OR contract_id IN (SELECT id FROM demo_test_contracts)"))
    connection.execute(sa.text("DELETE FROM order_redirect WHERE old_order_id IN (SELECT id FROM demo_test_orders) OR order_id IN (SELECT id FROM demo_test_orders)"))
    connection.execute(sa.text("DELETE FROM document WHERE id IN (SELECT id FROM demo_test_documents)"))
    connection.execute(sa.text("UPDATE orders SET previous_order_id = NULL WHERE id NOT IN (SELECT id FROM demo_test_orders) AND previous_order_id IN (SELECT id FROM demo_test_orders)"))
    connection.execute(sa.text("DELETE FROM orders WHERE id IN (SELECT id FROM demo_test_orders)"))
    connection.execute(sa.text("DELETE FROM additional_agreement WHERE id IN (SELECT id FROM demo_test_agreements)"))
    connection.execute(sa.text("DELETE FROM application WHERE id IN (SELECT id FROM demo_test_applications)"))
    connection.execute(sa.text("DELETE FROM contract WHERE id IN (SELECT id FROM demo_test_contracts)"))
    connection.execute(sa.text("DELETE FROM organization WHERE id IN (SELECT id FROM demo_test_organizations)"))
    connection.execute(sa.text("DELETE FROM specialty WHERE code IN ('TEST-01', 'TEST-02', 'TEST-03', 'TEST-04') AND NOT EXISTS (SELECT 1 FROM order_item WHERE order_item.specialty_id = specialty.id)"))
    connection.execute(sa.text("DELETE FROM faculty WHERE name IN ('Тестовый факультет А', 'Тестовый факультет Б') AND NOT EXISTS (SELECT 1 FROM contract_faculty WHERE contract_faculty.faculty_id = faculty.id) AND NOT EXISTS (SELECT 1 FROM application_faculty WHERE application_faculty.faculty_id = faculty.id) AND NOT EXISTS (SELECT 1 FROM order_item WHERE order_item.faculty_id = faculty.id)"))

    # PRE-PRODUCTION AUDIT CLEANUP ONLY.  Keep a concise, readable record of
    # the first real MТЗ import (organization, contract, order and import
    # summary) plus all BNTU settings changes.  Development logins, repeated
    # imports and mutations of test documents are intentionally removed.
    connection.execute(sa.text("CREATE TEMP TABLE demo_keep_audit (id BIGINT PRIMARY KEY) ON COMMIT DROP"))
    connection.execute(sa.text("""
        WITH real_import AS (
            SELECT timestamp
              FROM audit_log
             WHERE action = 'FILE_UPLOAD'
               AND entity_type = 'excel_import'
               AND diff #>> '{new,filename}' = 'МТЗ-из базы.xlsx'
               AND diff #>> '{new,rows_processed}' = '60'
             ORDER BY id
             LIMIT 1
        )
        INSERT INTO demo_keep_audit(id)
        SELECT audit_log.id
          FROM audit_log, real_import
         WHERE audit_log.timestamp = real_import.timestamp
           AND (
               (audit_log.action = 'CREATE' AND audit_log.entity_type IN ('organization', 'contract', 'order'))
               OR (audit_log.action = 'FILE_UPLOAD' AND audit_log.entity_type = 'excel_import')
           )
        UNION
        SELECT id FROM audit_log WHERE entity_type = 'app_setting'
        ON CONFLICT DO NOTHING
    """))
    connection.execute(sa.text("""
        WITH RECURSIVE ancestors(id, parent_event_id) AS (
            SELECT a.id, a.parent_event_id
              FROM audit_log a
              JOIN demo_keep_audit kept ON kept.id = a.id
            UNION
            SELECT parent.id, parent.parent_event_id
              FROM audit_log parent
              JOIN ancestors child ON child.parent_event_id = parent.id
        )
        INSERT INTO demo_keep_audit(id)
        SELECT id FROM ancestors
        ON CONFLICT DO NOTHING
    """))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log"))
    connection.execute(sa.text("""
        DO $$
        DECLARE deleted_rows integer;
        BEGIN
            LOOP
                DELETE FROM audit_log candidate
                 WHERE NOT EXISTS (SELECT 1 FROM demo_keep_audit kept WHERE kept.id = candidate.id)
                   AND NOT EXISTS (SELECT 1 FROM audit_log child WHERE child.parent_event_id = candidate.id);
                GET DIAGNOSTICS deleted_rows = ROW_COUNT;
                EXIT WHEN deleted_rows = 0;
            END LOOP;
        END $$
    """))
    connection.execute(sa.text("""
        CREATE TRIGGER trg_audit_log_immutable
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation()
    """))


def downgrade():
    raise NotImplementedError("The pre-production cleanup is intentionally irreversible; restore the verified backup instead.")
