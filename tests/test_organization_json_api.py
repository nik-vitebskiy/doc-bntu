from sqlalchemy import select

from app.models import AuditLog, Organization


def test_create_organization_with_minimal_and_full_payload(client, session):
    minimal = client.post("/api/organizations", json={"short_name": "ОАО \"МТЗ\""})
    assert minimal.status_code == 201, minimal.text
    assert minimal.json()["short_name"] == 'ОАО "МТЗ"'
    assert minimal.json()["full_name"] == 'ОАО "МТЗ"'
    assert minimal.json()["contracts"] == []
    assert minimal.json()["applications"] == []

    full = client.post("/api/organizations", json={
        "short_name": "ОАО \"МТЗ\"",
        "full_name": "Открытое акционерное общество «Минский тракторный завод»",
        "legal_address": "220070, г. Минск, ул. Долгобродская, 29",
        "authority": "Министерство промышленности",
        "phone": "+375 17 246-60-09",
        "unp": "100316761",
    })
    assert full.status_code == 201, full.text
    assert full.json() == {
        "id": full.json()["id"],
        "unp": "100316761",
        "short_name": 'ОАО "МТЗ"',
        "full_name": "Открытое акционерное общество «Минский тракторный завод»",
        "legal_address": "220070, г. Минск, ул. Долгобродская, 29",
        "authority": "Министерство промышленности",
        "phone": "+375 17 246-60-09",
        "contracts": [],
        "applications": [],
    }
    assert session.scalar(select(Organization).where(Organization.id == full.json()["id"])) is not None
    create_events = session.scalars(select(AuditLog).where(
        AuditLog.entity_type == "organization",
        AuditLog.action == "CREATE",
    )).all()
    assert len(create_events) == 2


def test_update_organization_requisites_and_audit(client, session):
    created = client.post("/api/organizations", json={
        "short_name": "Исходное название",
        "unp": "100000001",
    })
    organization_id = created.json()["id"]

    updated = client.put(f"/api/organizations/{organization_id}", json={
        "short_name": "Новое название",
        "full_name": "Новое полное наименование",
        "legal_address": "г. Минск",
        "authority": "БНТУ",
        "phone": "+375 17 000-00-00",
        "unp": "100000002",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["short_name"] == "Новое название"
    assert updated.json()["full_name"] == "Новое полное наименование"
    assert updated.json()["legal_address"] == "г. Минск"
    assert updated.json()["authority"] == "БНТУ"
    assert updated.json()["phone"] == "+375 17 000-00-00"
    assert updated.json()["unp"] == "100000002"

    event = session.scalars(select(AuditLog).where(
        AuditLog.entity_type == "organization",
        AuditLog.entity_id == organization_id,
        AuditLog.action == "UPDATE",
    )).one()
    assert event.diff["old"]["short_name"] == "Исходное название"
    assert event.diff["new"]["short_name"] == "Новое название"
    assert event.diff["new"]["unp"] == "100000002"


def test_organization_unp_validation_and_not_found(client):
    invalid = client.post("/api/organizations", json={
        "short_name": "Некорректный УНП",
        "unp": "12345A789",
    })
    assert invalid.status_code == 422
    assert "УНП должен содержать 9 цифр" in invalid.text

    blank_name = client.post("/api/organizations", json={"short_name": "   "})
    assert blank_name.status_code == 422
    assert "Укажите краткое наименование" in blank_name.text

    missing = client.put("/api/organizations/999999", json={"short_name": "Нет"})
    assert missing.status_code == 404
