from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AppUser, AuditLog, Contract, Order, OrderItem, Specialty
from app.services.auth_service import hash_password


def test_admin_can_search_and_edit_specialty_directory(client, session):
    specialty = Specialty(
        code="SPEC-01",
        name="SPEC-01",
        profile=None,
        qualification="Инженер",
    )
    session.add(specialty)
    session.commit()

    page = client.get("/specialties", params={"q": "SPEC-01"})
    assert page.status_code == 200
    assert "Справочник специальностей" in page.text
    assert "SPEC-01" in page.text

    response = client.post(
        f"/specialties/{specialty.id}",
        data={
            "name": "Проектирование машин",
            "profile": "Автомобилестроение",
            "qualification": "Инженер-механик",
        },
    )
    assert response.status_code == 303
    session.expire_all()
    saved = session.get(Specialty, specialty.id)
    assert saved.code == "SPEC-01"
    assert saved.name == "Проектирование машин"
    assert saved.profile == "Автомобилестроение"
    assert saved.qualification == "Инженер-механик"
    assert session.scalar(select(AuditLog).where(
        AuditLog.entity_type == "specialty",
        AuditLog.entity_id == specialty.id,
        AuditLog.action == "UPDATE",
    )) is not None


def test_head_can_view_but_cannot_edit_specialty_directory(session):
    from app.main import app

    specialty = Specialty(code="HEAD-01", name="Название")
    head = AppUser(
        username="specialty-head",
        email="specialty-head@example.com",
        password_hash=hash_password("Head-password-123"),
        full_name="Руководитель",
        role="HEAD",
        must_change_password=False,
    )
    session.add_all([specialty, head])
    session.commit()

    with TestClient(app, follow_redirects=False) as browser:
        browser.post("/login", data={"username": head.username, "password": "Head-password-123"})
        page = browser.get("/specialties")
        assert page.status_code == 200
        assert "HEAD-01" in page.text
        assert "Редактирование доступно администратору" in page.text
        assert 'action="/specialties/' not in page.text
        assert browser.post(
            f"/specialties/{specialty.id}",
            data={"name": "Подмена", "profile": "", "qualification": ""},
        ).status_code == 403

    session.expire_all()
    assert session.get(Specialty, specialty.id).name == "Название"


def test_specialty_picker_autofills_profile_and_qualification_but_allows_override(
    client, session, contract
):
    specialty = Specialty(
        code="AUTO-01",
        name="Автомобильная техника",
        profile="Проектирование автомобилей",
        qualification="Инженер-механик",
    )
    session.add(specialty)
    session.commit()

    page = client.get(f"/organizations/{contract.organization_id}")
    assert page.status_code == 200
    assert 'data-profile="Проектирование автомобилей"' in page.text
    assert 'data-qualification="Инженер-механик"' in page.text

    faculty_id = contract.faculty_links[0].faculty_id
    response = client.post(
        f"/contracts/{contract.id}/items",
        data={
            "faculty_id": faculty_id,
            "specialty": specialty.code,
            "profile": "Профиль из документа",
            "qualification": "Квалификация из документа",
        },
    )
    assert response.status_code == 303
    item = session.scalar(select(OrderItem).where(OrderItem.specialty_id == specialty.id))
    assert item.profile == "Профиль из документа"
    assert item.qualification_value == "Квалификация из документа"


def test_specialty_update_backfills_only_empty_items_as_one_audit_event(
    client, session, contract
):
    specialty = Specialty(code="7-07-0732-01", name="7-07-0732-01")
    second_contract = Contract(
        organization_id=contract.organization_id,
        number="SECOND-2026",
        start_date=contract.start_date,
        status="Активен",
    )
    session.add_all([specialty, second_contract])
    session.flush()
    first_order = Order(
        organization_id=contract.organization_id,
        contract_id=contract.id,
        is_current=True,
        revision=1,
        status="CURRENT",
    )
    second_order = Order(
        organization_id=contract.organization_id,
        contract_id=second_contract.id,
        is_current=True,
        revision=1,
        status="CURRENT",
    )
    session.add_all([first_order, second_order])
    session.flush()
    empty_null = OrderItem(order_id=first_order.id, specialty_id=specialty.id)
    empty_spaces = OrderItem(
        order_id=second_order.id,
        specialty_id=specialty.id,
        profile="   ",
        qualification_value="",
    )
    manual = OrderItem(
        order_id=first_order.id,
        specialty_id=specialty.id,
        profile="Ручной профиль",
        qualification_value="Ручная квалификация",
    )
    session.add_all([empty_null, empty_spaces, manual])
    session.commit()

    response = client.put(f"/api/specialties/{specialty.id}", json={
        "name": "Геодезия",
        "profile": "test",
        "qualification": "Инженер",
    })
    assert response.status_code == 200
    session.expire_all()
    assert session.get(OrderItem, empty_null.id).profile == "test"
    assert session.get(OrderItem, empty_null.id).qualification_value == "Инженер"
    assert session.get(OrderItem, empty_spaces.id).profile == "test"
    assert session.get(OrderItem, empty_spaces.id).qualification_value == "Инженер"
    assert session.get(OrderItem, manual.id).profile == "Ручной профиль"
    assert session.get(OrderItem, manual.id).qualification_value == "Ручная квалификация"

    events = session.scalars(select(AuditLog).where(
        AuditLog.entity_type == "specialty",
        AuditLog.entity_id == specialty.id,
        AuditLog.action == "UPDATE",
    )).all()
    assert len(events) == 1
    assert events[0].comment == (
        "Дозаполнение из справочника: специальность 7-07-0732-01, обновлено 2 строк"
    )
    assert events[0].diff["old"]["profile"] is None
    assert events[0].diff["new"]["profile"] == "test"
    assert session.scalar(select(AuditLog).where(
        AuditLog.entity_type == "order_item",
        AuditLog.entity_id.in_([empty_null.id, empty_spaces.id]),
    )) is None

    legacy_empty = OrderItem(order_id=first_order.id, specialty_id=specialty.id)
    session.add(legacy_empty)
    session.commit()
    page = client.get(f"/organizations/{contract.organization_id}")
    assert "из справочника:" not in page.text
