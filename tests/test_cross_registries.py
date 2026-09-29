from datetime import date, timedelta

from sqlalchemy import select

from app.main import app
from app.models import (
    Application,
    Contract,
    ContractFaculty,
    Document,
    DocumentAttachment,
    Faculty,
)
from app.services.application_service import create_application
from app.services.document_registry_service import PAGE_SIZE, application_registry, contract_registry
from app.services.organization_service import save_item
from app.services.status_service import URGENCY_DUE_30, URGENCY_LATER


def _contract(session, organization, faculty, number, end_date, status="Активен"):
    contract = Contract(
        organization_id=organization.id,
        number=number,
        start_date=date(2026, 1, 15),
        end_date=end_date,
        status=status,
    )
    session.add(contract)
    session.flush()
    session.add(ContractFaculty(contract_id=contract.id, faculty_id=faculty.id))
    session.commit()
    return contract


def _scan(session, organization_id, user_id, *, contract_id=None, application_id=None):
    document = Document(
        organization_id=organization_id,
        contract_id=contract_id,
        application_id=application_id,
        type="contract" if contract_id else "application",
        status="SIGNED",
    )
    session.add(document)
    session.flush()
    session.add(DocumentAttachment(
        document_id=document.id,
        file_kind="signed_scan",
        original_name="scan.pdf",
        mime_type="application/pdf",
        size_bytes=4,
        content=b"scan",
        uploaded_by=user_id,
    ))
    session.commit()


def test_contract_registry_combines_search_filters_urgency_and_scan(
    session, organization, user, actor, client
):
    today = date.today()
    faculty = Faculty(name="Факультет реестра договоров")
    other = Faculty(name="Другой факультет")
    session.add_all([faculty, other])
    session.commit()
    target = _contract(session, organization, faculty, "РЕЕСТР-2026/01", today + timedelta(days=20))
    _contract(session, organization, faculty, "ЗАКРЫТ-2026/02", today + timedelta(days=20), "Закрыт")
    _contract(session, organization, other, "ДАЛЬНИЙ-2027/01", today + timedelta(days=120))
    save_item(
        session,
        target.id,
        "REG-01",
        "Инженер",
        {"faculty_id": str(faculty.id), "demand_2027": "2"},
        user_id=user.id,
        audit_actor=actor,
    )
    _scan(session, organization.id, user.id, contract_id=target.id)

    page, faculties, years, counts, urgency = contract_registry(
        session,
        query_text="РЕЕСТР-2026",
        faculty=faculty.name,
        status="Активен",
        end_year=str(target.end_date.year),
        urgency=URGENCY_DUE_30,
    )
    assert page.total == 1
    assert page.rows[0].contract.id == target.id
    assert page.rows[0].specialty_count == 1
    assert page.rows[0].contract.has_signed_scan is True
    assert counts[URGENCY_DUE_30] == 1
    assert counts[URGENCY_LATER] == 0
    assert urgency == URGENCY_DUE_30
    assert faculty.name in faculties
    assert target.end_date.year in {int(year) for year in years}

    response = client.get("/contracts", params={
        "q": "РЕЕСТР-2026",
        "faculty": faculty.name,
        "status": "Активен",
        "end_year": target.end_date.year,
        "urgency": URGENCY_DUE_30,
    })
    assert response.status_code == 200
    assert target.number in response.text
    assert "ЗАКРЫТ-2026/02" not in response.text
    assert "ДАЛЬНИЙ-2027/01" not in response.text
    assert f"/organizations/{organization.id}#contract-{target.id}" in response.text
    assert "Есть подписанный скан" in response.text
    assert "Документы" not in response.text


def test_application_registry_combines_search_faculty_status_and_scan(
    session, organization, user, actor, client
):
    target = create_application(
        session,
        organization.id,
        ["Факультет заявок"],
        "ЗАЯВКА-01",
        "2026-09-24",
        "2027-12-31",
        user.id,
        audit_actor=actor,
    )
    closed = create_application(
        session,
        organization.id,
        ["Факультет заявок"],
        "ЗАЯВКА-02",
        "",
        "",
        user.id,
        audit_actor=actor,
    )
    closed.status = "Закрыт"
    session.commit()
    _scan(session, organization.id, user.id, application_id=target.id)

    page, faculties = application_registry(
        session,
        query_text="ЗАЯВКА-01",
        faculty="Факультет заявок",
        status="Заявка",
    )
    assert page.total == 1
    assert page.rows[0].id == target.id
    assert page.rows[0].has_signed_scan is True
    assert "Факультет заявок" in faculties

    response = client.get("/applications", params={
        "q": organization.name,
        "faculty": "Факультет заявок",
        "status": "Заявка",
    })
    assert response.status_code == 200
    assert target.number in response.text
    assert closed.number not in response.text
    assert f"/applications/{target.id}" in response.text
    assert f"/organizations/{organization.id}" in response.text
    assert "Есть подписанный скан" in response.text
    assert "Дата подписания" in response.text
    assert "Действует до" in response.text
    assert "31.12.2027" in response.text
    assert "Дата получения" not in response.text
    assert "24.09.2026" in response.text

    card = client.get(f"/applications/{target.id}")
    assert card.status_code == 200
    assert 'href="/applications"' in card.text
    assert "Действует до" in card.text
    assert 'value="2027-12-31"' in card.text
    assert "Получена:" not in card.text


def test_application_is_created_without_received_date(session, organization, client):
    faculty = Faculty(name="Факультет срока заявки")
    session.add(faculty)
    session.commit()

    form = client.get(f"/organizations/{organization.id}/applications/new")
    assert form.status_code == 200
    assert "Дата получения" not in form.text
    assert "Действует до" in form.text

    response = client.post(
        f"/organizations/{organization.id}/applications",
        data={
            "faculty": faculty.name,
            "number": "З-СРОК",
            "signed_date": "2026-09-29",
            "date_end": "2027-09-29",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    application = session.scalar(select(Application).where(Application.number == "З-СРОК"))
    assert application.received_date is None
    assert application.date_end == date(2027, 9, 29)


def test_applications_registry_has_one_get_route():
    routes = [
        route for route in app.routes
        if getattr(route, "path", None) == "/applications" and "GET" in getattr(route, "methods", set())
    ]
    assert len(routes) == 1


def test_contract_registry_paginates_by_fifty(session, organization):
    faculty = Faculty(name="Факультет пагинации")
    session.add(faculty)
    session.commit()
    for index in range(PAGE_SIZE + 1):
        _contract(
            session,
            organization,
            faculty,
            f"PAGE-{index:02d}",
            date(2030, 1, 1) + timedelta(days=index),
        )

    first, *_ = contract_registry(session, faculty=faculty.name, page=1)
    second, *_ = contract_registry(session, faculty=faculty.name, page=2)

    assert first.total == PAGE_SIZE + 1
    assert first.pages == 2
    assert len(first.rows) == PAGE_SIZE
    assert len(second.rows) == 1
    assert second.page == 2
