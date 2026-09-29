from datetime import date

from sqlalchemy import select

from app.models import Application, Contract, Faculty, OrderItem, Specialty
from app.services.application_service import create_application


def test_contract_creation_requires_start_date_and_allows_empty_end_date(
    session, organization, client
):
    faculty = Faculty(name="Факультет формы договора")
    session.add(faculty)
    session.commit()

    missing_start = client.post(
        f"/organizations/{organization.id}/contract",
        data={
            "faculty": faculty.name,
            "number": "DATE-INVALID",
            "start_date": "",
            "end_date": "2030-01-01",
        },
    )
    assert missing_start.status_code == 303
    assert "contract_date_error_field=start_date" in missing_start.headers["location"]
    error_page = client.get(missing_start.headers["location"])
    assert error_page.status_code == 200
    assert "Укажите дату начала договора." in error_page.text
    assert session.scalar(select(Contract).where(Contract.number == "DATE-INVALID")) is None

    created = client.post(
        f"/organizations/{organization.id}/contract",
        data={
            "faculty": faculty.name,
            "number": "DATE-VALID",
            "start_date": "2026-09-28",
            "end_date": "",
        },
    )
    assert created.status_code == 303
    contract = session.scalar(select(Contract).where(Contract.number == "DATE-VALID"))
    assert contract is not None
    assert contract.start_date == date(2026, 9, 28)
    assert contract.end_date is None


def test_contract_end_date_cannot_precede_start_date(session, organization, client):
    faculty = Faculty(name="Факультет проверки дат")
    session.add(faculty)
    session.commit()

    response = client.post(
        f"/organizations/{organization.id}/contract",
        data={
            "faculty": faculty.name,
            "number": "DATE-RANGE",
            "start_date": "2026-09-28",
            "end_date": "2026-09-27",
        },
    )

    assert response.status_code == 303
    assert "contract_date_error_field=end_date" in response.headers["location"]
    page = client.get(response.headers["location"])
    assert "Дата окончания не может быть раньше даты начала." in page.text


def test_application_status_comment_is_optional_in_both_directions(
    session, organization, user, actor, client
):
    application = create_application(
        session,
        organization.id,
        ["Факультет заявки без комментария"],
        "APP-NO-COMMENT",
        "",
        "",
        user.id,
        audit_actor=actor,
    )

    closed = client.post(
        f"/applications/{application.id}/status",
        data={"status": "Закрыт", "comment": ""},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "Закрыт"

    reopened = client.post(
        f"/applications/{application.id}/status",
        data={"status": "Заявка", "comment": ""},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "Заявка"
    session.expire_all()
    assert session.get(Application, application.id).status == "Заявка"


def test_main_registry_searches_organization_full_name(contract, organization, client):
    response = client.get("/", params={"q": "Полное тестовое наименование"})

    assert response.status_code == 200
    assert contract.number in response.text
    assert organization.name in response.text


def test_order_item_web_form_only_accepts_specialty_from_catalog(
    session, contract, client
):
    specialty = Specialty(
        code="CATALOG-01",
        name="Специальность из справочника",
        qualification="Инженер",
    )
    session.add(specialty)
    specialty_without_qualification = Specialty(
        code="CATALOG-02",
        name="Специальность без квалификации",
        qualification=None,
    )
    session.add(specialty_without_qualification)
    session.commit()
    faculty_id = contract.faculty_links[0].faculty_id

    page = client.get(f"/organizations/{contract.organization_id}")
    assert page.status_code == 200
    assert "data-specialty-picker" in page.text
    assert "CATALOG-01 — Специальность из справочника" in page.text
    assert 'data-qualification="Инженер"' in page.text
    assert 'data-value="CATALOG-02"' in page.text

    rejected = client.post(
        f"/contracts/{contract.id}/items",
        data={"faculty_id": faculty_id, "specialty": "TYPO-01", "qualification": ""},
    )
    assert rejected.status_code == 400
    assert "Выберите специальность из справочника." in rejected.text
    assert session.scalar(select(Specialty).where(Specialty.code == "TYPO-01")) is None

    accepted = client.post(
        f"/contracts/{contract.id}/items",
        data={
            "faculty_id": faculty_id,
            "specialty": specialty.code,
            "qualification": "Инженер документа",
        },
    )
    assert accepted.status_code == 303
    item = session.scalar(select(OrderItem).where(OrderItem.specialty_id == specialty.id))
    assert item is not None
    assert item.qualification_value == "Инженер документа"

    changed = client.post(
        f"/items/{item.id}",
        data={
            "faculty_id": faculty_id,
            "specialty": specialty_without_qualification.code,
            "qualification": "",
        },
    )
    assert changed.status_code == 303
    session.expire_all()
    assert item.specialty_id == specialty_without_qualification.id
    assert item.qualification_value is None

