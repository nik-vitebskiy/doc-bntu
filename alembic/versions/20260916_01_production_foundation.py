"""Add production foundation for access, document versions, and audit."""

from alembic import op


revision = "20260916_01"
down_revision = "20260915_00"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS full_name varchar(255)")
    op.execute("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS role varchar(30) NOT NULL DEFAULT 'SYSTEM'")
    op.execute("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_login_at timestamptz")

    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_faculty (
            contract_id bigint NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
            faculty_id bigint NOT NULL REFERENCES faculty(id),
            PRIMARY KEY (contract_id, faculty_id)
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'contract' AND column_name = 'faculty_id'
            ) THEN
                INSERT INTO contract_faculty(contract_id, faculty_id)
                SELECT id, faculty_id FROM contract ON CONFLICT DO NOTHING;
            END IF;
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS application (
            id bigserial PRIMARY KEY,
            organization_id bigint NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
            number varchar(100) NOT NULL,
            signed_date date NOT NULL,
            status varchar(30) NOT NULL DEFAULT 'Заявка',
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by bigint REFERENCES app_user(id),
            CONSTRAINT uq_application_number UNIQUE (organization_id, number)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS application_faculty (
            application_id bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
            faculty_id bigint NOT NULL REFERENCES faculty(id),
            PRIMARY KEY (application_id, faculty_id)
        )
    """)

    op.execute("ALTER TABLE additional_agreement ADD COLUMN IF NOT EXISTS status varchar(30) NOT NULL DEFAULT 'Активен'")
    op.execute("ALTER TABLE additional_agreement ADD COLUMN IF NOT EXISTS previous_agreement_id bigint REFERENCES additional_agreement(id)")
    op.execute("ALTER TABLE additional_agreement ADD COLUMN IF NOT EXISTS activated_at timestamptz")

    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS additional_agreement_id bigint REFERENCES additional_agreement(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS application_id bigint REFERENCES application(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS previous_order_id bigint REFERENCES orders(id)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_current boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1")
    op.execute("UPDATE orders SET status = 'CURRENT' WHERE status = 'DRAFT'")

    op.execute("ALTER TABLE order_item ADD COLUMN IF NOT EXISTS qualification varchar(255)")
    op.execute("ALTER TABLE order_item ADD COLUMN IF NOT EXISTS profile varchar(255)")
    op.execute("UPDATE order_item oi SET qualification = s.qualification FROM specialty s WHERE oi.specialty_id = s.id AND oi.qualification IS NULL")

    op.execute("ALTER TABLE document ADD COLUMN IF NOT EXISTS additional_agreement_id bigint REFERENCES additional_agreement(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE document ADD COLUMN IF NOT EXISTS application_id bigint REFERENCES application(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE document ADD COLUMN IF NOT EXISTS original_filename varchar(500)")
    op.execute("UPDATE document SET original_filename = file_id WHERE original_filename IS NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id bigserial PRIMARY KEY,
            user_id bigint REFERENCES app_user(id) ON DELETE SET NULL,
            action varchar(100) NOT NULL,
            entity_type varchar(50) NOT NULL,
            entity_id bigint,
            details text,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id)")
    op.execute("DROP TABLE IF EXISTS organization_representative")


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
