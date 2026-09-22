from datetime import datetime, timedelta, timezone

from app.models import AuditLog, ContractRedirect, OrderRedirect
from app.services.audit_registry_service import get_audit_registry
from app.services.organization_service import delete_organization, get_or_create_order


def _row(user_id, index, *, action="UPDATE", entity_type="contract", label=None, comment=None):
    return AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=10_000 + index,
        entity_label=label or f"Договор TEST-{index:03d}",
        diff={"old": {"status": "Активен"}, "new": {"status": f"Закрыт-{index}"}},
        comment=comment,
        sequence=1,
        timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
    )


def test_combined_registry_filters(session, user):
    other = _row(None, 1, action="CREATE", entity_type="organization", label="Организация Другая")
    matching = _row(
        user.id,
        2,
        action="STATUS_CHANGE",
        entity_type="contract",
        label="Договор ФИЛЬТР-2026",
        comment="Причина расторжения",
    )
    outside_period = _row(
        user.id,
        3,
        action="STATUS_CHANGE",
        entity_type="contract",
        label="Договор ФИЛЬТР-СТАРЫЙ",
    )
    outside_period.timestamp = datetime(2026, 8, 1, tzinfo=timezone.utc)
    session.add_all([other, matching, outside_period])
    session.commit()

    page = get_audit_registry(
        session,
        user=str(user.id),
        entity="contract",
        action="STATUS_CHANGE",
        date_from=datetime(2026, 9, 1).date(),
        date_to=datetime(2026, 9, 1).date(),
        query="расторжения",
    )
    assert page.total == 1
    assert page.rows[0].id == matching.id

    by_diff = get_audit_registry(session, query="Закрыт-2")
    assert [row.id for row in by_diff.rows] == [matching.id]


def test_login_is_hidden_by_default_and_visible_by_filter(session, user):
    login = _row(user.id, 1, action="LOGIN", entity_type="app_user", label="Пользователь Тестовый")
    update = _row(user.id, 2)
    session.add_all([login, update])
    session.commit()

    default_page = get_audit_registry(session)
    assert [row.id for row in default_page.rows] == [update.id]
    login_page = get_audit_registry(session, action="LOGIN")
    assert [row.id for row in login_page.rows] == [login.id]


def test_pagination_is_fifty_and_newest_first(session, user):
    session.add_all([_row(user.id, index) for index in range(55)])
    session.commit()

    first = get_audit_registry(session, page=1)
    second = get_audit_registry(session, page=2)
    assert first.total == 55
    assert first.pages == 2
    assert len(first.rows) == 50
    assert len(second.rows) == 5
    assert [row.entity_label for row in first.rows[:3]] == [
        "Договор TEST-054", "Договор TEST-053", "Договор TEST-052"
    ]
    assert second.rows[-1].entity_label == "Договор TEST-000"


def test_deleted_entity_keeps_label_without_link(session, organization, actor):
    label = f"Организация {organization.short_name}"
    delete_organization(session, organization, audit_actor=actor)
    page = get_audit_registry(session, action="DELETE", entity="organization")
    assert page.total == 1
    assert page.rows[0].entity_label == label
    assert page.rows[0].entity_url is None


def test_audit_page_renders_without_raw_json(session, user, client):
    session.add(_row(user.id, 1, action="STATUS_CHANGE", comment="Тестовый комментарий"))
    session.commit()
    response = client.get("/audit?action=STATUS_CHANGE")
    assert response.status_code == 200
    assert "Журнал действий" in response.text
    assert "Смена статуса" in response.text
    assert "Тестовый комментарий" in response.text
    assert '"old"' not in response.text


def test_historical_contract_and_order_events_link_to_merged_contract(session, contract, user):
    order = get_or_create_order(session, contract, user.id)
    session.add(ContractRedirect(old_contract_id=9001, contract_id=contract.id))
    session.add(OrderRedirect(old_order_id=9002, order_id=order.id))
    session.add_all([
        AuditLog(user_id=user.id, action="CREATE", entity_type="contract", entity_id=9001,
                 entity_label="Исторический договор", diff={"new": {"number": contract.number}}, sequence=1),
        AuditLog(user_id=user.id, action="CREATE", entity_type="order", entity_id=9002,
                 entity_label="Исторический заказ", diff={"new": {}}, sequence=2),
    ])
    session.commit()
    rows = get_audit_registry(session).rows
    urls = {row.entity_type: row.entity_url for row in rows if row.entity_label.startswith("Исторический")}
    assert urls["contract"] == f"/organizations/{contract.organization_id}?audit_highlight=contract-{contract.id}"
    assert urls["order"] == f"/organizations/{contract.organization_id}"
