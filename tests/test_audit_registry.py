from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import (
    AdditionalAgreement, AnnualDemand, AppSetting, AppUser, Application,
    ApplicationFaculty, AuditLog, Contract, ContractFaculty, Document,
    DocumentAttachment, Faculty, Order, OrderItem, OrderRedirect,
    ContractRedirect, Organization, Specialty,
)
from app.services.audit_metadata import FIELD_LABELS, HIDDEN_DIFF_FIELDS
from app.services.audit_registry_service import ACTION_LABELS, ENTITY_FILTERS, _diff_lines, get_audit_registry
from app.services.audit_service import AuditAction
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


def test_development_actions_and_demo_user_are_not_filter_options(session):
    session.add(AppUser(username="demo", password_hash="unused", full_name="Техническая учётка"))
    session.commit()

    registry = get_audit_registry(session)

    assert "ACTIVATE" not in ACTION_LABELS
    assert "SEED_TEST_DATA" not in ACTION_LABELS
    assert all(user.username != "demo" for user in registry.users)


def test_employee_facing_audit_labels_are_explicit():
    assert ENTITY_FILTERS["order"][0] == "Строка заказа"
    assert ACTION_LABELS["COPY"] == "Копирование заказа (активация д.с.)"
    assert all("Черновик" not in label for label in ACTION_LABELS.values())


def test_every_audited_model_field_has_a_russian_label_or_is_hidden():
    models = (
        Organization, Contract, ContractFaculty, AdditionalAgreement,
        Application, ApplicationFaculty, Order, OrderItem, AnnualDemand,
        Specialty, Faculty, Document, DocumentAttachment, AppUser, AppSetting,
    )
    special_fields = {"password_hash", "content"}
    missing = {
        f"{model.__tablename__}.{column.key}"
        for model in models
        for column in model.__mapper__.column_attrs
        if column.key not in FIELD_LABELS
        and column.key not in HIDDEN_DIFF_FIELDS
        and column.key not in special_fields
    }
    assert missing == set()


@pytest.mark.parametrize(("entity_type", "values"), [
    ("organization", {"unp": "100000000", "short_name": "ОАО МТЗ", "full_name": "ОАО МТЗ", "legal_address": "Минск", "authority": "Минпром", "phone": "+375"}),
    ("contract", {"number": "221", "start_date": "2026-01-01", "end_date": "2030-01-01", "status": "Активен"}),
    ("additional_agreement", {"number": "1", "date": "2026-01-01", "status": "Активен", "previous_agreement_id": "№0", "activated_at": "2026-01-01T10:00:00+03:00"}),
    ("application", {"number": "З-1", "received_date": "2026-01-01", "signed_date": "2026-01-02", "status": "Заявка"}),
    ("order", {"status": "CURRENT", "is_current": True, "previous_order_id": "Заказ договора №221"}),
    ("order_item", {"specialty_id": "7-01-01", "faculty_id": "Автотракторный", "qualification": "Инженер", "profile": "Профиль"}),
    ("annual_demand", {"year": 2027, "quantity": 5}),
    ("specialty", {"code": "7-01-01", "name": "Испытание", "qualification": "Инженер", "faculty": "Автотракторный"}),
    ("faculty", {"name": "Автотракторный", "code": "АТФ"}),
    ("document", {"type": "CONTRACT", "status": "CURRENT"}),
    ("document_attachment", {"file_kind": "signed_scan", "original_name": "scan.pdf", "mime_type": "application/pdf", "size_bytes": 100}),
    ("excel_import", {"filename": "МТЗ.xlsx", "rows_processed": 60, "organizations": 1, "contracts_created": 1, "order_items_created": 60, "faculty_links_created": 11}),
    ("app_user", {"username": "head", "full_name": "Руководитель", "role": "HEAD", "is_active": True, "must_change_password": False, "password": "изменён"}),
    ("app_setting", {"key": "audit_login_enabled", "value": True, "description": "Фиксировать входы"}),
])
def test_every_real_event_payload_has_named_fields(entity_type, values):
    lines = _diff_lines(entity_type, {"old": {}, "new": values})
    assert len(lines) == len(values)
    assert all(line.label and line.label != "Поле" for line in lines)


def test_documentation_covers_all_filter_types_and_actions():
    documentation = Path("docs/audit-event-types.md").read_text(encoding="utf-8")
    assert set(ACTION_LABELS) == {action.value for action in AuditAction}
    assert all(label in documentation for label, _types in ENTITY_FILTERS.values())
    assert all(label in documentation for label in ACTION_LABELS.values())


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


def test_legacy_draft_is_rendered_as_effective_status_without_mutating_event(session, user):
    row = AuditLog(
        user_id=user.id,
        action="CREATE",
        entity_type="order",
        entity_id=77,
        entity_label="Заказ договора №TEST",
        diff={"old": {}, "new": {"id": 77, "contract_id": 1, "revision": 1, "status": "DRAFT"}},
        sequence=1,
    )
    session.add(row)
    session.commit()

    rendered = get_audit_registry(session).rows[0]
    assert [(line.label, line.new) for line in rendered.diff_lines] == [("Статус", "Действующий")]
    assert session.get(AuditLog, row.id).diff["new"]["status"] == "DRAFT"


def test_legacy_import_is_readable_and_hides_internal_filename(session, user):
    row = AuditLog(
        user_id=user.id,
        action="FILE_UPLOAD",
        entity_type="excel_import",
        entity_id=None,
        entity_label="Импорт Excel МТЗ-из базы.xlsx",
        diff={"old": {}, "new": {
            "filename": "МТЗ-из базы.xlsx",
            "stored_name": "import-87f8b04c.xlsx",
            "rows_processed": 60,
            "organizations": 1,
            "contracts": 1,
            "faculties": 11,
            "specialties": 60,
        }},
        sequence=1,
    )
    session.add(row)
    session.commit()

    rendered = get_audit_registry(session, action="FILE_UPLOAD").rows[0]
    labels = [line.label for line in rendered.diff_lines]
    assert labels == [
        "Имя файла", "Обработано строк", "Загружено организаций",
        "Обработано договоров", "Обработано факультетов", "Обработано специальностей",
    ]
    assert "Поле" not in labels
    assert all("import-87f8b04c" not in line.new for line in rendered.diff_lines)


def test_unmapped_diff_field_is_warned_and_hidden(session, user, caplog):
    row = AuditLog(
        user_id=user.id,
        action="UPDATE",
        entity_type="contract",
        entity_id=1,
        entity_label="Договор TEST",
        diff={"old": {"future_field": "до"}, "new": {"future_field": "после"}},
        sequence=1,
    )
    session.add(row)
    session.commit()

    rendered = get_audit_registry(session).rows[0]
    assert rendered.diff_lines == []
    assert "entity_type=contract field=future_field" in caplog.text
    assert "Поле" not in caplog.text


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
