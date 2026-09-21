from datetime import date

from app.models import Contract, ContractFaculty, Faculty


def _contract(session, organization, number, start_date, *faculties):
    contract = Contract(
        organization_id=organization.id,
        number=number,
        start_date=start_date,
        status="Активен",
    )
    session.add(contract)
    session.flush()
    for faculty in faculties:
        session.add(ContractFaculty(contract_id=contract.id, faculty_id=faculty.id))
    session.commit()
    return contract


def test_registry_link_passes_selected_faculty_context(session, organization, client):
    faculty = Faculty(name="Горного дела и инженерной экологии")
    session.add(faculty)
    session.commit()
    contract = _contract(session, organization, "ГД-01", date(2026, 1, 10), faculty)

    response = client.get("/", params={"faculty": faculty.name})

    assert response.status_code == 200
    assert f"/organizations/{organization.id}?faculty_id={faculty.id}" in response.text
    assert contract.number in response.text


def test_organization_card_prioritizes_and_highlights_context_contracts(session, organization, client):
    context = Faculty(name="Горного дела и инженерной экологии")
    other = Faculty(name="Машиностроительный")
    session.add_all([context, other])
    session.commit()
    context_old = _contract(session, organization, "КОНТЕКСТ-СТАРЫЙ", date(2024, 1, 1), context)
    context_new = _contract(session, organization, "КОНТЕКСТ-НОВЫЙ", date(2025, 1, 1), context, other)
    unrelated_newest = _contract(session, organization, "ЧУЖОЙ-НОВЫЙ", date(2026, 1, 1), other)

    response = client.get(f"/organizations/{organization.id}", params={"faculty_id": context.id})

    assert response.status_code == 200
    html = response.text
    assert html.index(context_new.number) < html.index(context_old.number) < html.index(unrelated_newest.number)
    assert html.count("faculty-context-contract") == 2
    assert html.count("Ваш факультет") == 2
    assert "faculty-context-name" in html
    assert f"faculty_id={context.id}" in str(response.url)


def test_organization_card_without_context_keeps_date_order_and_no_highlight(session, organization, client):
    first = Faculty(name="Факультет А")
    second = Faculty(name="Факультет Б")
    session.add_all([first, second])
    session.commit()
    older = _contract(session, organization, "СТАРЫЙ", date(2024, 1, 1), first)
    newer = _contract(session, organization, "НОВЫЙ", date(2026, 1, 1), second)

    response = client.get(f"/organizations/{organization.id}")

    assert response.status_code == 200
    assert response.text.index(newer.number) < response.text.index(older.number)
    assert "faculty-context-contract" not in response.text
    assert "Ваш факультет" not in response.text


def test_unknown_or_unrelated_faculty_context_has_no_highlight(session, organization, client):
    faculty = Faculty(name="Факультет без договоров")
    other = Faculty(name="Факультет договора")
    session.add_all([faculty, other])
    session.commit()
    _contract(session, organization, "БЕЗ-КОНТЕКСТА", date(2026, 1, 1), other)

    response = client.get(f"/organizations/{organization.id}", params={"faculty_id": faculty.id})

    assert response.status_code == 200
    assert "faculty-context-contract" not in response.text
    assert "Ваш факультет" not in response.text

