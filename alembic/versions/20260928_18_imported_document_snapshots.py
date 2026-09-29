"""Add stable import snapshots and normalize the existing MTZ agreement."""

import sqlalchemy as sa
from alembic import op


revision = "20260928_18"
down_revision = "20260928_17"
branch_labels = None
depends_on = None


def _migrate_mtz(connection):
    connection.execute(sa.text(r"""
        DO $$
        DECLARE
            matched integer;
            old_contract bigint;
            old_order bigint;
            org_id bigint;
            new_contract bigint;
            base_order bigint;
            agreement_id bigint;
            agreement_order bigint;
            old_start date;
            old_end date;
        BEGIN
            SELECT count(*) INTO matched
              FROM contract c JOIN organization z ON z.id = c.organization_id
             WHERE z.unp = '100316761'
               AND btrim(c.number) = 'д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020';
            IF matched = 0 THEN RETURN; END IF;
            IF matched <> 1 THEN
                RAISE EXCEPTION 'MTZ migration expected one combined contract, found %', matched;
            END IF;

            SELECT c.id, c.organization_id, c.start_date, c.end_date
              INTO old_contract, org_id, old_start, old_end
              FROM contract c JOIN organization z ON z.id = c.organization_id
             WHERE z.unp = '100316761'
               AND btrim(c.number) = 'д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020';
            IF (SELECT count(*) FROM orders WHERE contract_id = old_contract) <> 1 THEN
                RAISE EXCEPTION 'MTZ migration requires exactly one source order';
            END IF;
            SELECT id INTO old_order FROM orders WHERE contract_id = old_contract;
            IF (SELECT count(*) FROM order_item WHERE order_id = old_order) <> 60 THEN
                RAISE EXCEPTION 'MTZ migration requires exactly 60 source rows';
            END IF;
            IF EXISTS (SELECT 1 FROM additional_agreement WHERE contract_id = old_contract) THEN
                RAISE EXCEPTION 'MTZ combined contract already has agreements';
            END IF;
            IF EXISTS (
                SELECT 1 FROM document d
                LEFT JOIN document_attachment a ON a.document_id = d.id
                WHERE d.contract_id = old_contract
                  AND (d.type <> 'CONTRACT' OR a.id IS NOT NULL)
            ) THEN
                RAISE EXCEPTION 'MTZ combined contract has files/documents requiring manual classification';
            END IF;
            IF EXISTS (SELECT 1 FROM contract WHERE organization_id = org_id AND number = '221-АТФ/280') THEN
                RAISE EXCEPTION 'Normalized MTZ contract already exists';
            END IF;

            INSERT INTO contract(organization_id, number, start_date, end_date, status)
            VALUES (org_id, '221-АТФ/280', DATE '2020-10-01', old_end, 'Закрыт')
            RETURNING id INTO new_contract;
            INSERT INTO contract_faculty(contract_id, faculty_id)
            SELECT new_contract, faculty_id FROM contract_faculty WHERE contract_id = old_contract;
            INSERT INTO additional_agreement(contract_id, number, date, status, activated_at)
            VALUES (new_contract, '1', DATE '2025-05-06', 'Активен', now())
            RETURNING id INTO agreement_id;
            INSERT INTO orders(organization_id, contract_id, is_current, revision, status, import_key)
            VALUES (org_id, new_contract, false, 1, 'REPLACED', 'contract:' || new_contract)
            RETURNING id INTO base_order;
            INSERT INTO orders(organization_id, contract_id, additional_agreement_id, previous_order_id,
                               is_current, revision, status, import_key)
            VALUES (org_id, new_contract, agreement_id, base_order, true, 2, 'CURRENT',
                    'additional_agreement:' || agreement_id)
            RETURNING id INTO agreement_order;
            UPDATE order_item SET order_id = agreement_order WHERE order_id = old_order;
            INSERT INTO contract_redirect(old_contract_id, contract_id) VALUES (old_contract, new_contract)
            ON CONFLICT (old_contract_id) DO UPDATE SET contract_id = EXCLUDED.contract_id;
            INSERT INTO order_redirect(old_order_id, order_id) VALUES (old_order, agreement_order)
            ON CONFLICT (old_order_id) DO UPDATE SET order_id = EXCLUDED.order_id;
            UPDATE document SET contract_id = new_contract WHERE contract_id = old_contract;
            DELETE FROM orders WHERE id = old_order;
            DELETE FROM contract WHERE id = old_contract;
        END $$;
    """))


def upgrade():
    op.add_column("orders", sa.Column("import_key", sa.String(255), nullable=True))
    op.create_index("uq_orders_import_key", "orders", ["import_key"], unique=True)
    _migrate_mtz(op.get_bind())


def downgrade():
    raise NotImplementedError("Imported snapshot migration is intentionally forward-only.")
