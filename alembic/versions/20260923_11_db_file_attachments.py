"""Store all document attachments in PostgreSQL instead of /uploads."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op


revision = "20260923_11"
down_revision = "20260923_10"
branch_labels = None
depends_on = None


def _uploads_path() -> Path:
    return Path(os.getenv("UPLOAD_DIR", "uploads"))


def upgrade():
    op.create_table(
        "document_attachment",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.BigInteger(), sa.ForeignKey("document.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_kind", sa.String(30), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_attachment_size_nonnegative"),
    )
    op.create_index("ix_document_attachment_document_id", "document_attachment", ["document_id"])
    op.create_index("ix_document_attachment_file_kind", "document_attachment", ["file_kind"])
    op.create_index("ix_document_attachment_uploaded_by", "document_attachment", ["uploaded_by"])
    op.create_index("ix_document_attachment_deleted_at", "document_attachment", ["deleted_at"])

    connection = op.get_bind()
    uploads = _uploads_path()
    migrated_paths: list[Path] = []
    legacy_rows = connection.execute(sa.text("""
        SELECT id, type, file_id, original_filename
          FROM document
         WHERE file_id IS NOT NULL AND file_id <> ''
    """)).mappings()
    for row in legacy_rows:
        path = uploads / Path(row["file_id"]).name
        if not path.is_file():
            raise RuntimeError(f"Не найден старый файл документа: {path}")
        content = path.read_bytes()
        original_name = row["original_filename"] or path.name
        mime_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        file_kind = "signed_scan" if row["type"] == "SIGNED_SCAN" else "source_file"
        attachment_id = connection.scalar(sa.text("""
            INSERT INTO document_attachment(
                document_id, file_kind, original_name, mime_type, size_bytes, content
            ) VALUES (
                :document_id, :file_kind, :original_name, :mime_type, :size_bytes, :content
            ) RETURNING id
        """), {
            "document_id": row["id"],
            "file_kind": file_kind,
            "original_name": original_name,
            "mime_type": mime_type,
            "size_bytes": len(content),
            "content": content,
        })
        stored_size = connection.scalar(
            sa.text("SELECT octet_length(content) FROM document_attachment WHERE id = :id"),
            {"id": attachment_id},
        )
        if stored_size != path.stat().st_size:
            raise RuntimeError(f"Размер перенесённого файла не совпал: {path}")
        migrated_paths.append(path)

    connection.execute(sa.text("""
        UPDATE document
           SET type = CASE
               WHEN additional_agreement_id IS NOT NULL THEN 'ADDITIONAL_AGREEMENT'
               WHEN application_id IS NOT NULL THEN 'APPLICATION'
               ELSE 'CONTRACT'
           END
    """))
    op.drop_column("document", "original_filename")
    op.drop_column("document", "file_id")

    # Only verified files are removed. Unrelated or orphaned files remain on
    # disk for a deliberate manual review instead of being silently discarded.
    for path in migrated_paths:
        path.unlink()


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
