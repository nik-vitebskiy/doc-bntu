from datetime import date, timedelta

from app.models import Contract, ContractFaculty, Faculty
from app.services.organization_service import registry
from app.services.status_service import (
    URGENCY_DUE_30,
    URGENCY_DUE_90,
    URGENCY_LATER,
    expiry_urgency,
)


def test_expiry_urgency_boundaries():
    today = date(2026, 9, 23)
    cases = (
        (None, None, None),
        (today - timedelta(days=1), URGENCY_DUE_30, True),
        (today, URGENCY_DUE_30, False),
        (today + timedelta(days=29), URGENCY_DUE_30, False),
        (today + timedelta(days=30), URGENCY_DUE_30, False),
        (today + timedelta(days=31), URGENCY_DUE_90, False),
        (today + timedelta(days=90), URGENCY_DUE_90, False),
        (today + timedelta(days=91), URGENCY_LATER, False),
    )
    expected_classes = {
        URGENCY_DUE_30: "danger",
        URGENCY_DUE_90: "warning",
        URGENCY_LATER: "success",
    }
    for end_date, bucket, overdue in cases:
        result = expiry_urgency(end_date, today)
        if bucket is None:
            assert result is None
        else:
            assert (result.bucket, result.css_class, result.overdue) == (
                bucket, expected_classes[bucket], overdue,
            )


def _add_contract(session, organization, faculty, number, end_date):
    contract = Contract(
        organization_id=organization.id,
        number=number,
        start_date=date.today(),
        end_date=end_date,
        status="Активен",
    )
    session.add(contract)
    session.flush()
    session.add(ContractFaculty(contract_id=contract.id, faculty_id=faculty.id))
    return contract


def test_registry_filters_buckets_counts_and_puts_overdue_first(session, organization):
    today = date.today()
    faculty = Faculty(name="Факультет срочности")
    session.add(faculty)
    session.flush()
    contracts = {
        "Просроченный": today - timedelta(days=10),
        "Сегодня": today,
        "30 дней": today + timedelta(days=30),
        "31 день": today + timedelta(days=31),
        "90 дней": today + timedelta(days=90),
        "91 день": today + timedelta(days=91),
        "Без даты": None,
    }
    for number, end_date in contracts.items():
        _add_contract(session, organization, faculty, number, end_date)
    session.commit()

    rows, _, _, _, _, counts = registry(session, faculty=faculty.name, urgency=URGENCY_DUE_30)

    assert [row.contract.number for row in rows] == ["Просроченный", "Сегодня", "30 дней"]
    assert counts == {URGENCY_DUE_30: 3, URGENCY_DUE_90: 2, URGENCY_LATER: 1}
    assert all(row.expiry.bucket == URGENCY_DUE_30 for row in rows)
    assert rows[0].expiry.overdue is True
    assert all(row.contract.number != "Без даты" for row in rows)


def test_urgency_combines_with_end_year_and_ui_toggles(client, session, organization):
    faculty = Faculty(name="Факультет фильтров")
    session.add(faculty)
    session.flush()
    today = date.today()
    this_year_date = min(today + timedelta(days=20), date(today.year, 12, 31))
    next_year_date = date(today.year + 1, 1, 15)
    _add_contract(session, organization, faculty, "ЭТОТ-ГОД", this_year_date)
    _add_contract(session, organization, faculty, "СЛЕДУЮЩИЙ-ГОД", next_year_date)
    session.commit()

    rows, _, _, _, _, counts = registry(
        session,
        faculty=faculty.name,
        end_year=str(today.year),
        urgency=URGENCY_DUE_30,
    )
    assert [row.contract.number for row in rows] == ["ЭТОТ-ГОД"]
    assert counts[URGENCY_DUE_30] == 1

    page = client.get("/", params={"faculty": faculty.name, "end_year": today.year, "urgency": URGENCY_DUE_30})
    assert page.status_code == 200
    assert 'value="due_30" class="urgency-toggle urgency-due_30 active"' in page.text
    assert "≤ 30 дней <span>1</span>" in page.text
    assert "ЭТОТ-ГОД" in page.text
    assert "СЛЕДУЮЩИЙ-ГОД" not in page.text

    toggle_off = client.get("/", params={
        "faculty": faculty.name,
        "end_year": today.year,
        "urgency": URGENCY_DUE_30,
        "urgency_choice": URGENCY_DUE_30,
    })
    assert toggle_off.status_code == 303
    assert "urgency=" not in toggle_off.headers["location"]
