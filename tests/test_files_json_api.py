from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AppUser, Application, AuditLog, Faculty, Order, Specialty
from app.services.auth_service import hash_password
from app.services.organization_service import register_additional_agreement


def test_contract_files_api_upload_list_download_delete_restore(client, session, contract):
    uploaded = client.post(
        f"/api/contracts/{contract.id}/files",
        data={"file_kind": "signed_scan"},
        files={"file": ("подписанный договор.pdf", b"pdf-content", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    metadata = uploaded.json()
    file_id = metadata["id"]
    assert metadata["original_name"] == "подписанный договор.pdf"
    assert metadata["size_bytes"] == len(b"pdf-content")
    assert metadata["file_kind"] == "signed_scan"
    assert metadata["uploaded_by"] is not None
    assert metadata["uploaded_at"]

    listed = client.get(f"/api/contracts/{contract.id}/files")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [file_id]
    card = client.get(f"/api/contracts/{contract.id}")
    assert card.json()["has_signed_scan"] is True

    downloaded = client.get(f"/api/files/{file_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"pdf-content"
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]

    deleted = client.delete(f"/api/files/{file_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/files/{file_id}/download").status_code == 404
    assert client.get(f"/api/contracts/{contract.id}/files").json() == []
    deleted_list = client.get(
        f"/api/contracts/{contract.id}/files", params={"include_deleted": "true"},
    ).json()
    assert deleted_list[0]["id"] == file_id
    assert deleted_list[0]["deleted_at"] is not None

    restored = client.post(f"/api/files/{file_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    actions = session.scalars(select(AuditLog.action).where(
        AuditLog.entity_type == "document_attachment",
        AuditLog.entity_id == file_id,
    ).order_by(AuditLog.id)).all()
    assert actions == ["FILE_UPLOAD", "FILE_DELETE", "FILE_RESTORE"]


def test_application_and_agreement_files_api_use_same_service(
    client, session, organization, contract, user, actor
):
    application = Application(
        organization_id=organization.id,
        number="APP-FILES",
        status="Заявка",
        created_by=user.id,
    )
    session.add(application)
    session.commit()
    agreement = register_additional_agreement(
        session, contract, "1", date(2026, 10, 1), user.id, audit_actor=actor,
    )

    for path, filename in (
        (f"applications/{application.id}", "заявка.png"),
        (f"additional-agreements/{agreement.id}", "соглашение.png"),
    ):
        response = client.post(
            f"/api/{path}/files",
            data={"file_kind": "source_file"},
            files={"file": (filename, b"png", "image/png")},
        )
        assert response.status_code == 201, response.text
        assert client.get(f"/api/{path}/files").json()[0]["original_name"] == filename


def test_files_api_rejects_executable_generated_kind_and_oversize(
    client, contract, monkeypatch
):
    executable = client.post(
        f"/api/contracts/{contract.id}/files",
        data={"file_kind": "source_file"},
        files={"file": ("payload.exe", b"bad", "application/octet-stream")},
    )
    assert executable.status_code == 422
    assert "PDF, JPG, PNG и DOCX" in executable.json()["detail"]

    generated = client.post(
        f"/api/contracts/{contract.id}/files",
        data={"file_kind": "generated_docx"},
        files={"file": (
            "generated.docx",
            b"PK",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )},
    )
    assert generated.status_code == 422

    monkeypatch.setattr("app.services.file_service.MAX_FILE_SIZE", 10)
    oversized = client.post(
        f"/api/contracts/{contract.id}/files",
        data={"file_kind": "source_file"},
        files={"file": ("large.pdf", b"x" * 11, "application/pdf")},
    )
    assert oversized.status_code == 422
    assert "50 МБ" in oversized.json()["detail"]


def test_file_delete_restore_permissions_and_deleted_visibility(client, session, contract):
    uploaded = client.post(
        f"/api/contracts/{contract.id}/files",
        data={"file_kind": "source_file"},
        files={"file": ("admin.pdf", b"admin", "application/pdf")},
    ).json()
    head = AppUser(
        username="file-head",
        email="file-head@example.com",
        password_hash=hash_password("Head-password-123"),
        full_name="Руководитель файлов",
        role="HEAD",
        must_change_password=False,
    )
    session.add(head)
    session.commit()

    from app.main import app
    with TestClient(app, follow_redirects=False) as browser:
        assert browser.post("/api/auth/login", json={
            "username": head.username,
            "password": "Head-password-123",
        }).status_code == 200
        forbidden = browser.delete(f"/api/files/{uploaded['id']}")
        assert forbidden.status_code == 403

        own = browser.post(
            f"/api/contracts/{contract.id}/files",
            data={"file_kind": "source_file"},
            files={"file": ("head.pdf", b"head", "application/pdf")},
        ).json()
        assert browser.delete(f"/api/files/{own['id']}").status_code == 204
        own_deleted = browser.get(
            f"/api/contracts/{contract.id}/files",
            params={"include_deleted": "true"},
        ).json()
        assert {row["id"] for row in own_deleted} == {uploaded["id"], own["id"]}
        assert browser.post(f"/api/files/{own['id']}/restore").status_code == 200

    assert client.delete(f"/api/files/{uploaded['id']}").status_code == 204
    with TestClient(app, follow_redirects=False) as browser:
        browser.post("/api/auth/login", json={
            "username": head.username,
            "password": "Head-password-123",
        })
        visible = browser.get(
            f"/api/contracts/{contract.id}/files",
            params={"include_deleted": "true"},
        ).json()
        assert uploaded["id"] not in {row["id"] for row in visible}


def test_first_and_second_application_order_items_share_current_revision(
    client, session, organization, user
):
    faculty = Faculty(name="Факультет API заявки")
    first_specialty = Specialty(code="APP-API-01", name="Первая")
    second_specialty = Specialty(code="APP-API-02", name="Вторая")
    application = Application(
        organization_id=organization.id,
        number="APP-WITHOUT-ORDER",
        status="Заявка",
        created_by=user.id,
    )
    session.add_all([faculty, first_specialty, second_specialty, application])
    session.commit()
    assert application.current_order is None

    first = client.post(f"/api/applications/{application.id}/order-items", json={
        "faculty_id": faculty.id,
        "specialty_id": first_specialty.id,
        "profile": None,
        "qualification": "Инженер",
        "years": {"2027": 2},
    })
    assert first.status_code == 201, first.text
    session.expire_all()
    order = session.scalar(select(Order).where(Order.application_id == application.id))
    assert order.is_current is True
    assert len(order.items) == 1

    second = client.post(f"/api/applications/{application.id}/order-items", json={
        "faculty_id": faculty.id,
        "specialty_id": second_specialty.id,
        "profile": "Профиль",
        "qualification": None,
        "years": {"2028": 3},
    })
    assert second.status_code == 201, second.text
    session.expire_all()
    orders = session.scalars(select(Order).where(Order.application_id == application.id)).all()
    assert len(orders) == 1
    assert orders[0].is_current is True
    assert [item.specialty_id for item in orders[0].items] == [first_specialty.id, second_specialty.id]
