import traceback

from sqlalchemy import event, func, select

from app.models import AppUser, AuditLog, Faculty, Specialty, engine
from app.services.file_service import AttachmentError, MAX_FILE_SIZE, validate_attachment
from fastapi.testclient import TestClient


def test_organization_contract_and_application_bad_forms_are_422(client, organization):
    response = client.post("/organizations/new", data={"name": ""})
    assert response.status_code == 422
    assert "Краткое наименование обязательно" in response.text

    response = client.post(
        f"/organizations/{organization.id}/contract",
        data={"faculty": "Тестовый", "number": "", "start_date": "bad", "end_date": "2020-01-01"},
    )
    assert response.status_code == 422
    assert "Номер договора обязателен" in response.text

    response = client.post(
        f"/organizations/{organization.id}/applications",
        data={"faculty": "Тестовый", "number": "", "signed_date": "2027-02-01", "date_end": "2027-01-01"},
    )
    assert response.status_code == 422
    assert "Номер заявки обязателен" in response.text


def test_contract_date_order_and_duplicate_warning(client, session, organization, contract):
    faculty = session.query(Faculty).filter(Faculty.name == "Тестовый факультет").one()
    response = client.post(
        f"/contracts/{contract.id}",
        data={"faculty": faculty.name, "number": contract.number, "start_date": "2030-01-02", "end_date": "2030-01-01"},
    )
    assert response.status_code == 422
    assert "не может быть раньше" in response.text

    response = client.post(
        f"/organizations/{organization.id}/contract",
        data={"faculty": faculty.name, "number": contract.number, "start_date": "2026-01-01", "end_date": ""},
    )
    assert response.status_code == 200
    assert "уже есть договор с номером" in response.text


def test_order_item_rejects_missing_dictionary_values_and_bad_demands(client, session, contract):
    faculty = session.query(Faculty).filter(Faculty.name == "Тестовый факультет").one()
    specialty = Specialty(code="VALID-01", name="Валидная")
    session.add(specialty)
    session.commit()

    for data, text in (
        ({"faculty_id": "", "specialty": specialty.code, "demand_2027": "1"}, "Факультет"),
        ({"faculty_id": str(faculty.id), "specialty": "", "demand_2027": "1"}, "Специальность"),
        ({"faculty_id": str(faculty.id), "specialty": specialty.code, "demand_2027": "-1"}, "отрицательным"),
        ({"faculty_id": str(faculty.id), "specialty": specialty.code, "demand_2037": "1"}, "2026–2036"),
    ):
        response = client.post(f"/contracts/{contract.id}/items", data=data)
        assert response.status_code == 422
        assert text in response.text


def test_user_validation_is_russian(client):
    response = client.post("/users/new", data={
        "full_name": "Тест", "username": "ab", "role": "HEAD",
        "initial_password": "short", "password_repeat": "short",
    })
    assert response.status_code == 422
    assert "не менее 3" in response.text

    response = client.post("/change-password", data={
        "current_password": "Test-password-123", "new_password": "short", "password_repeat": "short",
    })
    assert response.status_code == 422
    assert "не менее 8" in response.text


def test_additional_agreement_requires_number_and_date(client, contract):
    response = client.post(
        f"/contracts/{contract.id}/additional-agreements",
        data={"number": "", "agreement_date": "bad-date"},
    )
    assert response.status_code == 422
    assert "Номер дополнительного соглашения обязателен" in response.text

def test_file_errors_are_readable_for_exe_and_60_mb():
    for name, content, expected in (
        ("virus.exe", b"MZ", "PDF, JPG, PNG и DOCX"),
        ("large.pdf", b"x" * (MAX_FILE_SIZE + 1), "50 МБ"),
    ):
        try:
            validate_attachment(name, "application/pdf", content)
        except AttachmentError as error:
            assert expected in str(error)
        else:
            raise AssertionError("Ожидалась понятная ошибка файла")


def test_unexpected_exception_has_friendly_page(monkeypatch):
    def fail():
        raise RuntimeError("secret traceback marker")

    monkeypatch.setattr("app.main.show_docs_enabled", fail)
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as browser:
        response = browser.get("/docs")
    assert response.status_code == 500
    assert "Произошла ошибка" in response.text
    assert "secret traceback marker" not in response.text


def test_failed_forms_never_mutate_existing_audit_rows(client, session):
    statements = []

    def catch_audit_mutation(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.upper().replace('"', "").split())
        if normalized.startswith(("UPDATE AUDIT_LOG", "DELETE FROM AUDIT_LOG")):
            statements.append((statement, "".join(traceback.format_stack())))

    audit_count = session.scalar(select(func.count(AuditLog.id)))
    admin = session.scalar(select(AppUser).where(AppUser.username == "test-admin"))
    event.listen(engine, "before_cursor_execute", catch_audit_mutation)
    try:
        blocked = client.post(f"/users/{admin.id}/edit", data={
            "full_name": admin.full_name,
            "role": "HEAD",
        })
        invalid = client.post("/organizations/new", data={"name": ""})
    finally:
        event.remove(engine, "before_cursor_execute", catch_audit_mutation)

    assert blocked.status_code == 400
    assert invalid.status_code == 422
    assert statements == [], "Запрещённая мутация audit_log:\n" + "\n".join(
        f"{sql}\n{stack}" for sql, stack in statements
    )
    assert session.scalar(select(func.count(AuditLog.id))) == audit_count
