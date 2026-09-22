"""Keep one contract per organization and number; assign order lines to faculties."""

from alembic import op


revision = "20260922_09"
down_revision = "20260922_08"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE order_item ADD COLUMN faculty_id bigint REFERENCES faculty(id)")
    op.execute("CREATE INDEX idx_order_item_faculty ON order_item(faculty_id)")
    op.execute("""
        CREATE TABLE contract_redirect (
            old_contract_id bigint PRIMARY KEY,
            contract_id bigint NOT NULL REFERENCES contract(id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE order_redirect (
            old_order_id bigint PRIMARY KEY,
            order_id bigint NOT NULL REFERENCES orders(id) ON DELETE CASCADE
        )
    """)
    # A legacy one-faculty contract identifies the owner of every order line.
    op.execute("""
        UPDATE order_item AS item
        SET faculty_id = link.faculty_id
        FROM orders AS ord
        JOIN contract_faculty AS link ON link.contract_id = ord.contract_id
        WHERE item.order_id = ord.id
          AND (SELECT count(*) FROM contract_faculty WHERE contract_id = ord.contract_id) = 1
    """)
    # An old multi-faculty order has no reliable row-level provenance. Stop
    # rather than infer a faculty from specialty text or arbitrary ordering.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM order_item i JOIN orders o ON o.id = i.order_id
                WHERE o.contract_id IS NOT NULL AND i.faculty_id IS NULL
            ) THEN
                RAISE EXCEPTION 'Contract order items without an unambiguous faculty require manual resolution';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE order_item DROP CONSTRAINT IF EXISTS uq_order_specialty")
    op.execute("ALTER TABLE order_item ADD CONSTRAINT uq_order_faculty_specialty UNIQUE(order_id, faculty_id, specialty_id)")

    op.execute("""
        DO $$
        DECLARE group_row record; source_row record; target_order bigint;
        BEGIN
            FOR group_row IN
                SELECT organization_id, number, min(id) AS target_id
                FROM contract GROUP BY organization_id, number HAVING count(*) > 1
            LOOP
                IF EXISTS (
                    SELECT 1 FROM contract c JOIN contract target ON target.id = group_row.target_id
                    WHERE c.organization_id = group_row.organization_id
                      AND c.number = group_row.number
                      AND (c.status, c.start_date, c.end_date)
                          IS DISTINCT FROM (target.status, target.start_date, target.end_date)
                ) THEN
                    RAISE EXCEPTION 'Conflicting dates or statuses for contract %', group_row.number;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM additional_agreement a JOIN contract c ON c.id = a.contract_id
                    WHERE c.organization_id = group_row.organization_id AND c.number = group_row.number
                ) OR EXISTS (
                    SELECT 1 FROM document d JOIN contract c ON c.id = d.contract_id
                    WHERE c.organization_id = group_row.organization_id AND c.number = group_row.number
                ) THEN
                    RAISE EXCEPTION 'Agreements or documents need manual review for contract %', group_row.number;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM contract c LEFT JOIN orders o ON o.contract_id = c.id
                    WHERE c.organization_id = group_row.organization_id AND c.number = group_row.number
                    GROUP BY c.id HAVING count(o.id) <> 1
                ) THEN
                    RAISE EXCEPTION 'Expected one order per legacy contract %', group_row.number;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM orders o JOIN contract c ON c.id = o.contract_id
                    WHERE c.organization_id = group_row.organization_id AND c.number = group_row.number
                      AND (o.additional_agreement_id IS NOT NULL OR o.previous_order_id IS NOT NULL
                           OR o.revision <> 1 OR o.is_current IS NOT TRUE)
                ) THEN
                    RAISE EXCEPTION 'Contract % has order revisions requiring manual review', group_row.number;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM orders o JOIN contract c ON c.id = o.contract_id
                    JOIN orders child ON child.previous_order_id = o.id
                    WHERE c.organization_id = group_row.organization_id AND c.number = group_row.number
                ) THEN
                    RAISE EXCEPTION 'Contract % has dependent orders', group_row.number;
                END IF;
                SELECT id INTO target_order FROM orders WHERE contract_id = group_row.target_id;
                IF EXISTS (
                    SELECT 1 FROM order_item i JOIN orders o ON o.id = i.order_id
                    JOIN contract c ON c.id = o.contract_id
                    WHERE c.organization_id = group_row.organization_id AND c.number = group_row.number
                    GROUP BY i.faculty_id, i.specialty_id HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION 'Duplicate faculty/specialty lines for contract %', group_row.number;
                END IF;
                FOR source_row IN
                    SELECT c.id, o.id AS order_id FROM contract c
                    JOIN orders o ON o.contract_id = c.id
                    WHERE c.organization_id = group_row.organization_id
                      AND c.number = group_row.number AND c.id <> group_row.target_id
                LOOP
                    INSERT INTO contract_redirect(old_contract_id, contract_id)
                    VALUES (source_row.id, group_row.target_id);
                    INSERT INTO order_redirect(old_order_id, order_id)
                    VALUES (source_row.order_id, target_order);
                    INSERT INTO contract_faculty(contract_id, faculty_id)
                    SELECT group_row.target_id, faculty_id FROM contract_faculty
                    WHERE contract_id = source_row.id ON CONFLICT DO NOTHING;
                    UPDATE order_item SET order_id = target_order WHERE order_id = source_row.order_id;
                    DELETE FROM orders WHERE id = source_row.order_id;
                    DELETE FROM contract WHERE id = source_row.id;
                END LOOP;
            END LOOP;
        END $$;
    """)
    op.execute("ALTER TABLE contract ADD CONSTRAINT uq_contract_organization_number UNIQUE(organization_id, number)")


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
