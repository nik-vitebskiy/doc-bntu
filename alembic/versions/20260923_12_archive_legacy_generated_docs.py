"""Archive identifiable legacy generated DOCX files in the database."""

from __future__ import annotations

import os
import re
from pathlib import Path

import sqlalchemy as sa
from alembic import op


revision = "20260923_12"
down_revision = "20260923_11"
branch_labels = None
depends_on = None


LEGACY_GENERATED_NAME = re.compile(r"^Дополнительное_соглашение_(\d+)\.docx$", re.IGNORECASE)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upgrade():
    connection = op.get_bind()
    uploads = Path(os.getenv("UPLOAD_DIR", "uploads"))
    if not uploads.is_dir():
        return
    migrated: list[Path] = []
    for path in uploads.iterdir():
        match = LEGACY_GENERATED_NAME.match(path.name)
        if not match or not path.is_file():
            continue
        contract_id = int(match.group(1))
        organization_id = connection.scalar(
            sa.text("SELECT organization_id FROM contract WHERE id = :id"), {"id": contract_id}
        )
        if organization_id is None:
            continue
        document_id = connection.scalar(sa.text("""
            SELECT id FROM document WHERE contract_id = :contract_id ORDER BY id LIMIT 1
        """), {"contract_id": contract_id})
        if document_id is None:
            document_id = connection.scalar(sa.text("""
                INSERT INTO document(organization_id, contract_id, type, version, status)
                VALUES (:organization_id, :contract_id, 'CONTRACT', 1, 'CURRENT')
                RETURNING id
            """), {"organization_id": organization_id, "contract_id": contract_id})
        content = path.read_bytes()
        duplicate = connection.scalar(sa.text("""
            SELECT id FROM document_attachment
             WHERE document_id = :document_id AND file_kind = 'generated_docx'
               AND original_name = :name AND size_bytes = :size
             LIMIT 1
        """), {"document_id": document_id, "name": path.name, "size": len(content)})
        if duplicate is None:
            attachment_id = connection.scalar(sa.text("""
                INSERT INTO document_attachment(
                    document_id, file_kind, original_name, mime_type, size_bytes, content
                ) VALUES (:document_id, 'generated_docx', :name, :mime, :size, :content)
                RETURNING id
            """), {
                "document_id": document_id,
                "name": path.name,
                "mime": DOCX_MIME,
                "size": len(content),
                "content": content,
            })
            stored_size = connection.scalar(
                sa.text("SELECT octet_length(content) FROM document_attachment WHERE id = :id"),
                {"id": attachment_id},
            )
            if stored_size != path.stat().st_size:
                raise RuntimeError(f"Размер перенесённого файла не совпал: {path}")
        migrated.append(path)
    for path in migrated:
        path.unlink()


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
