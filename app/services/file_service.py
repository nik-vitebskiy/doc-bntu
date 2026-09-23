from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import select, text
from sqlalchemy.orm import Session, defer, joinedload

from ..models import AdditionalAgreement, Application, Contract, Document, DocumentAttachment, SessionLocal
from .audit_service import AuditAction, audited, current_audit_batch


MAX_FILE_SIZE = 50 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
MANUAL_FILE_KINDS = {"signed_scan", "source_file"}
FILE_KIND_LABELS = {
    "signed_scan": "Подписанный скан",
    "generated_docx": "Сформированный документ",
    "source_file": "Исходник от организации",
}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class AttachmentError(ValueError):
    pass


def validate_attachment(filename: str, mime_type: str, content: bytes, *, generated: bool = False) -> tuple[str, str]:
    safe_name = Path(filename or "").name.strip()
    if not safe_name:
        raise AttachmentError("У файла отсутствует имя.")
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AttachmentError("Разрешены только PDF, JPG, PNG и DOCX.")
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in ALLOWED_MIME_TYPES:
        raise AttachmentError("Тип файла не соответствует PDF, JPG, PNG или DOCX.")
    if not content:
        raise AttachmentError("Нельзя загрузить пустой файл.")
    if len(content) > MAX_FILE_SIZE:
        raise AttachmentError("Файл превышает допустимый размер 50 МБ.")
    if generated and extension != ".docx":
        raise AttachmentError("Сформированный системой документ должен быть DOCX.")
    return safe_name[:500], normalized_mime


def _document_for(
    session: Session,
    *,
    contract: Contract | None = None,
    application: Application | None = None,
    agreement: AdditionalAgreement | None = None,
) -> Document:
    entities = [entity for entity in (contract, application, agreement) if entity is not None]
    if len(entities) != 1:
        raise AttachmentError("Файл должен относиться ровно к одному документу.")
    if contract:
        document = session.scalar(select(Document).where(Document.contract_id == contract.id).order_by(Document.id).limit(1))
        if not document:
            document = Document(organization_id=contract.organization_id, contract_id=contract.id, type="CONTRACT", status="CURRENT")
    elif application:
        document = session.scalar(select(Document).where(Document.application_id == application.id).order_by(Document.id).limit(1))
        if not document:
            document = Document(organization_id=application.organization_id, application_id=application.id, type="APPLICATION", status="CURRENT")
    else:
        document = session.scalar(select(Document).where(Document.additional_agreement_id == agreement.id).order_by(Document.id).limit(1))
        if not document:
            document = Document(
                organization_id=agreement.contract.organization_id,
                additional_agreement_id=agreement.id,
                type="ADDITIONAL_AGREEMENT",
                status="CURRENT",
            )
    if document.id is None:
        current_audit_batch(session).suppress(document)
        session.add(document)
        session.flush()
    return document


@audited
def create_attachment(
    session: Session,
    *,
    filename: str,
    mime_type: str,
    content: bytes,
    file_kind: str,
    uploaded_by: int | None,
    contract: Contract | None = None,
    application: Application | None = None,
    agreement: AdditionalAgreement | None = None,
) -> DocumentAttachment:
    if file_kind not in {*MANUAL_FILE_KINDS, "generated_docx"}:
        raise AttachmentError("Выбран неизвестный тип файла.")
    safe_name, normalized_mime = validate_attachment(filename, mime_type, content, generated=file_kind == "generated_docx")
    document = _document_for(session, contract=contract, application=application, agreement=agreement)
    attachment = DocumentAttachment(
        document=document,
        file_kind=file_kind,
        original_name=safe_name,
        mime_type=normalized_mime,
        size_bytes=len(content),
        content=content,
        uploaded_by=uploaded_by,
    )
    session.add(attachment)
    return attachment


def _audit_values(attachment: DocumentAttachment) -> dict:
    return {
        "document_id": attachment.document_id,
        "file_kind": attachment.file_kind,
        "original_name": attachment.original_name,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "uploaded_by": attachment.uploaded_by,
    }


@audited
def delete_attachment(session: Session, attachment: DocumentAttachment, actor_id: int, actor_role: str) -> DocumentAttachment:
    if attachment.deleted_at is not None:
        raise AttachmentError("Файл уже удалён.")
    if attachment.file_kind == "generated_docx":
        raise AttachmentError("Сформированный системой документ удалять нельзя.")
    if actor_role != "ADMIN" and attachment.uploaded_by != actor_id:
        raise AttachmentError("Удалить файл может только его автор или администратор.")
    old = _audit_values(attachment)
    attachment.deleted_at = datetime.now(timezone.utc)
    current_audit_batch(session).record(
        attachment,
        AuditAction.FILE_DELETE,
        old=old,
        new={"deleted_at": attachment.deleted_at.isoformat()},
    )
    return attachment


@audited
def restore_attachment(session: Session, attachment: DocumentAttachment, actor_id: int, actor_role: str) -> DocumentAttachment:
    if attachment.deleted_at is None:
        raise AttachmentError("Файл не удалён.")
    if actor_role != "ADMIN" and attachment.uploaded_by != actor_id:
        raise AttachmentError("Восстановить файл может только его автор или администратор.")
    old_deleted_at = attachment.deleted_at.isoformat()
    attachment.deleted_at = None
    current_audit_batch(session).record(
        attachment,
        AuditAction.FILE_RESTORE,
        old={"deleted_at": old_deleted_at},
        new=_audit_values(attachment) | {"deleted_at": None},
    )
    return attachment


def get_attachment_metadata(session: Session, attachment_id: int, *, include_deleted: bool = False) -> DocumentAttachment | None:
    statement = (
        select(DocumentAttachment)
        .options(defer(DocumentAttachment.content), joinedload(DocumentAttachment.document), joinedload(DocumentAttachment.uploader))
        .where(DocumentAttachment.id == attachment_id)
    )
    if not include_deleted:
        statement = statement.where(DocumentAttachment.deleted_at.is_(None))
    return session.scalar(statement)


def stream_attachment(attachment_id: int, chunk_size: int = DOWNLOAD_CHUNK_SIZE) -> Iterator[bytes]:
    """Yield BYTEA slices without materialising the full value in Python."""
    session = SessionLocal()
    try:
        offset = 1
        while True:
            chunk = session.execute(
                text("""
                    SELECT substring(content FROM :offset FOR :chunk_size)
                      FROM document_attachment
                     WHERE id = :attachment_id AND deleted_at IS NULL
                """),
                {"offset": offset, "chunk_size": chunk_size, "attachment_id": attachment_id},
            ).scalar_one_or_none()
            if not chunk:
                break
            yield bytes(chunk)
            offset += len(chunk)
    finally:
        session.close()


def attachment_destination(attachment: DocumentAttachment) -> str:
    document = attachment.document
    if document.application_id:
        return f"/applications/{document.application_id}"
    if document.additional_agreement_id:
        return f"/additional-agreements/{document.additional_agreement_id}/comparison"
    return f"/organizations/{document.organization_id}"
