"""Expand audit storage and make it immutable."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260917_05"
down_revision = "20260917_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_log", sa.Column("entity_label", sa.String(500), nullable=True))
    op.add_column(
        "audit_log",
        sa.Column(
            "diff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{\"old\": {}, \"new\": {}}'::jsonb"),
        ),
    )
    op.add_column("audit_log", sa.Column("comment", sa.Text(), nullable=True))
    op.add_column("audit_log", sa.Column("ip_address", sa.String(45), nullable=True))
    op.add_column("audit_log", sa.Column("parent_event_id", sa.BigInteger(), nullable=True))
    op.add_column("audit_log", sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "audit_log",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.execute("UPDATE audit_log SET comment = details WHERE details IS NOT NULL")
    op.execute("UPDATE audit_log SET timestamp = created_at")
    op.execute(
        "UPDATE audit_log SET entity_label = entity_type || "
        "CASE WHEN entity_id IS NULL THEN '' ELSE '/' || entity_id::text END"
    )
    op.alter_column("audit_log", "entity_label", nullable=False)
    op.alter_column("audit_log", "timestamp", nullable=False)
    op.drop_column("audit_log", "details")
    op.drop_column("audit_log", "created_at")

    op.create_foreign_key(
        "fk_audit_log_parent",
        "audit_log",
        "audit_log",
        ["parent_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_audit_log_user", "audit_log", ["user_id"])
    op.create_index("idx_audit_log_timestamp", "audit_log", [sa.text('"timestamp" DESC')])
    op.create_index("idx_audit_log_parent_sequence", "audit_log", ["parent_event_id", "sequence"])
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX idx_audit_log_entity_label_trgm "
        "ON audit_log USING gin (entity_label gin_trgm_ops)"
    )

    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute(
        "INSERT INTO app_setting(key, value, description) VALUES "
        "('audit_login_enabled', 'true'::jsonb, 'Фиксировать входы пользователей в журнале') "
        "ON CONFLICT (key) DO NOTHING"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_immutable
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation()
        """
    )


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
