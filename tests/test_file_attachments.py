import pytest
from sqlalchemy import select

from app.models import DocumentAttachment
from app.services.file_service import (
    AttachmentError,
    MAX_FILE_SIZE,
    create_attachment,
    stream_attachment,
    validate_attachment,
)
from app.services.application_service import create_application
from app.services.organization_service import register_additional_agreement
from datetime import date


def test_rejects_disallowed_extension_and_oversize_file():
    with pytest.raises(AttachmentError, match="PDF, JPG, PNG и DOCX"):
        validate_attachment("virus.exe", "application/octet-stream", b"bad")
    with pytest.raises(AttachmentError, match="50 МБ"):
        validate_attachment("large.pdf", "application/pdf", b"x" * (MAX_FILE_SIZE + 1))


def test_generated_document_is_not_an_attachment_kind(session, contract, actor, user):
    with pytest.raises(AttachmentError, match="неизвестный тип"):
        create_attachment(
            session,
            contract=contract,
            filename="generated.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=b"PK",
            file_kind="generated_docx",
            uploaded_by=user.id,
            audit_actor=actor,
        )


def test_streams_large_bytea_in_chunks_without_loading_model_content(session, contract, actor, user):
    content = b"x" * (41 * 1024 * 1024)
    attachment = create_attachment(
        session,
        contract=contract,
        filename="large.pdf",
        mime_type="application/pdf",
        content=content,
        file_kind="signed_scan",
        uploaded_by=user.id,
        audit_actor=actor,
    )
    attachment_id = attachment.id
    del content

    chunks = list(stream_attachment(attachment_id))
    assert len(chunks) == 41
    assert all(len(chunk) == 1024 * 1024 for chunk in chunks)
    assert sum(map(len, chunks)) == 41 * 1024 * 1024


def test_document_generation_route_is_removed(session, contract, client):
    response = client.get(f"/contracts/{contract.id}/agreement")
    assert response.status_code == 404
    page = client.get(f"/organizations/{contract.organization_id}")
    assert response.request.url.path not in page.text
    assert "Сформировать доп. соглашение" not in page.text


def test_file_upload_endpoint_rejects_executable(session, contract, client):
    response = client.post(
        f"/contracts/{contract.id}/files",
        data={"file_kind": "source_file"},
        files={"file": ("payload.exe", b"not executable", "application/octet-stream")},
    )
    assert response.status_code == 303
    assert "file_error=" in response.headers["location"]
    assert session.scalar(select(DocumentAttachment.id)) is None


def test_application_and_agreement_use_the_same_upload_flow(session, organization, contract, client, actor, user):
    application = create_application(
        session, organization.id, ["Тестовый факультет"], "2026-09-23", "APP-FILE-1", "",
        user.id, audit_actor=actor,
    )
    agreement = register_additional_agreement(
        session, contract, "DS-FILE-2", date(2026, 9, 23), user.id, audit_actor=actor,
    )
    for url, filename in (
        (f"/applications/{application.id}/files", "application.pdf"),
        (f"/additional-agreements/{agreement.id}/files", "agreement.pdf"),
    ):
        response = client.post(
            url,
            data={"file_kind": "source_file"},
            files={"file": (filename, b"source", "application/pdf")},
        )
        assert response.status_code == 303

    session.expire_all()
    attachments = session.scalars(select(DocumentAttachment).order_by(DocumentAttachment.id)).all()
    assert [row.original_name for row in attachments] == ["application.pdf", "agreement.pdf"]
    assert attachments[0].document.application_id == application.id
    assert attachments[1].document.additional_agreement_id == agreement.id
