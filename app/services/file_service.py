from __future__ import annotations

from ..models import Document
from .audit_service import audited


@audited
def delete_document(session, document: Document) -> dict[str, int | str | None]:
    """Delete file metadata; AuditBatch records immutable FILE_DELETE."""
    destination = {
        "organization_id": document.organization_id,
        "contract_id": document.contract_id,
        "application_id": document.application_id,
        "stored_name": document.stored_name,
    }
    session.delete(document)
    return destination
