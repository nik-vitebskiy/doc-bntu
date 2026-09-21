from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import event, func, select

from app.models import (
    AdditionalAgreement,
    AuditLog,
    Contract,
    Document,
    Order,
)
from app.services.audit_registry_service import get_audit_registry
from app.services.audit_service import AuditActor
from app.services.document_status_service import change_contract_status
from app.services.import_service import import_xlsx
from app.services.organization_service import delete_item, register_additional_agreement, save_item


def _after(session, audit_id):
    return session.scalars(select(AuditLog).where(AuditLog.id > audit_id).order_by(AuditLog.id)).all()


def _excel_bytes(organization="Импортируемая организация", unp="999200001"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Организация-заказчик", "УНП", "Факультет", "Номер договора",
        "Код специальности, направления специальности, специализации", "Квалификация", "2027",
    ])
    sheet.append([organization, unp, "Автотракторный", "IMP-01", "7-01-01", "Инженер", 3])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_status_change_is_separate_event_with_optional_comment(session, contract, actor):
    start = session.query(func.coalesce(func.max(AuditLog.id), 0)).scalar()
    change_contract_status(session, contract, "Закрыт", "ADMIN", "Закрыт сотрудником", audit_actor=actor)
    event_row = session.scalars(select(AuditLog).where(AuditLog.id > start)).one()
    assert event_row.action == "STATUS_CHANGE"
    assert event_row.diff == {"old": {"status": "Активен"}, "new": {"status": "Закрыт"}}
    assert event_row.comment == "Закрыт сотрудником"

    change_contract_status(session, contract, "Активен", "ADMIN", "", audit_actor=actor)
    reopened = session.scalars(select(AuditLog).where(AuditLog.id > event_row.id)).one()
    assert reopened.action == "STATUS_CHANGE"
    assert reopened.comment is None


def test_contract_status_api_accepts_closing_without_comment(session, contract, client):
    response = client.post(f"/contracts/{contract.id}/status", data={"status": "Закрыт", "comment": ""})
    assert response.status_code == 200
    session.expire_all()
    assert session.get(Contract, contract.id).status == "Закрыт"
    row = session.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "contract",
            AuditLog.entity_id == contract.id,
            AuditLog.action == "STATUS_CHANGE",
        )
    ).one()
    assert row.comment is None


def test_agreement_activation_creates_grouped_copy_and_chain(session, contract, user, actor):
    item = save_item(
        session,
        contract.id,
        "TEST-01",
        "Инженер",
        {"demand_2027": "2", "demand_2028": "4"},
        user_id=user.id,
        audit_actor=actor,
    )
    source_order_id = item.order_id
    start = session.query(func.coalesce(func.max(AuditLog.id), 0)).scalar()

    agreement = register_additional_agreement(
        session, contract, "ДС-01", date(2026, 9, 21), user.id, audit_actor=actor
    )
    events = _after(session, start)
    root = next(row for row in events if row.entity_type == "additional_agreement" and row.action == "CREATE")
    copies = [row for row in events if row.action == "COPY"]
    assert len(copies) == 1
    assert copies[0].parent_event_id == root.id
    assert copies[0].diff["new"]["rows_count"] == 1
    assert copies[0].diff["new"]["items"][0]["specialty"] == "TEST-01"
    assert not [row for row in events if row.action == "CREATE" and row.entity_type in {"order_item", "annual_demand"}]

    source_update = next(row for row in events if row.entity_type == "order" and row.action == "UPDATE")
    assert source_update.diff == {"old": {"is_current": True}, "new": {"is_current": False}}
    closed = next(row for row in events if row.entity_type == "contract" and row.action == "STATUS_CHANGE")
    assert closed.diff["new"]["status"] == "Закрыт"
    assert closed.parent_event_id == root.id
    assert session.get(Order, source_order_id).is_current is False
    assert session.get(AdditionalAgreement, agreement.id).status == "Активен"


def test_activation_failure_rolls_back_entire_chain(session, contract, user, actor):
    item = save_item(
        session, contract.id, "TEST-ROLLBACK", "Инженер", {"demand_2027": "1"},
        user_id=user.id, audit_actor=actor,
    )
    source_order_id = item.order_id
    audit_count = session.query(AuditLog).count()

    def fail_on_copy(_mapper, _connection, target):
        if target.action == "COPY":
            raise RuntimeError("copy audit failed")

    event.listen(AuditLog, "before_insert", fail_on_copy)
    try:
        with pytest.raises(RuntimeError, match="copy audit failed"):
            register_additional_agreement(
                session, contract, "ДС-FAIL", date(2026, 9, 21), user.id, audit_actor=actor
            )
    finally:
        event.remove(AuditLog, "before_insert", fail_on_copy)

    session.expire_all()
    assert session.scalar(select(AdditionalAgreement).where(AdditionalAgreement.number == "ДС-FAIL")) is None
    assert session.get(Contract, contract.id).status == "Активен"
    assert session.get(Order, source_order_id).is_current is True
    assert session.query(AuditLog).count() == audit_count


def test_order_item_and_demand_create_update_delete_are_audited(session, contract, user, actor):
    start = session.query(func.coalesce(func.max(AuditLog.id), 0)).scalar()
    item = save_item(
        session, contract.id, "TEST-ORDER", "Инженер", {"demand_2027": "2"},
        user_id=user.id, audit_actor=actor,
    )
    created = _after(session, start)
    item_create = next(row for row in created if row.entity_type == "order_item" and row.action == "CREATE")
    demand_create = next(row for row in created if row.entity_type == "annual_demand" and row.action == "CREATE")
    assert "Заказ договора" in item_create.entity_label and "TEST-ORDER" in item_create.entity_label
    assert "Заказ договора" in demand_create.entity_label and "TEST-ORDER" in demand_create.entity_label

    start = max(row.id for row in created)
    save_item(
        session, contract.id, "TEST-ORDER-NEW", "Инженер", {"demand_2027": "7"},
        item=item, user_id=user.id, audit_actor=actor,
    )
    updated = _after(session, start)
    item_update = next(row for row in updated if row.entity_type == "order_item" and row.action == "UPDATE")
    demand_update = next(row for row in updated if row.entity_type == "annual_demand" and row.action == "UPDATE")
    assert set(item_update.diff["new"]) == {"specialty_id"}
    assert demand_update.diff == {"old": {"quantity": 2}, "new": {"quantity": 7}}

    start = max(row.id for row in updated)
    delete_item(session, item, audit_actor=actor)
    deleted = _after(session, start)
    assert any(row.entity_type == "order_item" and row.action == "DELETE" for row in deleted)
    assert any(row.entity_type == "annual_demand" and row.action == "DELETE" for row in deleted)


def test_scan_upload_and_delete_are_audited_and_remove_file(session, contract, client):
    response = client.post(
        f"/contracts/{contract.id}/scan",
        files={"file": ("scan.pdf", b"test-pdf", "application/pdf")},
    )
    assert response.status_code == 303
    session.expire_all()
    document = session.scalars(select(Document).where(Document.contract_id == contract.id)).one()
    document_id = document.id
    upload = session.scalars(select(AuditLog).where(AuditLog.entity_id == document.id, AuditLog.action == "FILE_UPLOAD")).one()
    assert upload.diff["new"]["original_filename"] == "scan.pdf"

    from pathlib import Path
    stored_path = Path("uploads") / document.stored_name
    assert stored_path.is_file()
    response = client.post(f"/documents/{document_id}/delete")
    assert response.status_code == 303
    session.expire_all()
    assert session.get(Document, document_id) is None
    assert not stored_path.exists()
    deleted = session.scalars(select(AuditLog).where(AuditLog.entity_id == document_id, AuditLog.action == "FILE_DELETE")).one()
    assert deleted.diff["old"]["original_filename"] == "scan.pdf"
    registry = get_audit_registry(session, action="FILE_DELETE")
    assert registry.rows[0].file_name == "scan.pdf"
    assert registry.rows[0].file_url is None


def test_excel_import_records_current_user_and_system(session, client, tmp_path):
    response = client.post(
        "/import",
        files={"file": ("web-import.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 303
    session.expire_all()
    web_event = session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "excel_import", AuditLog.entity_label.contains("web-import"))
    ).one()
    assert web_event.user_id is not None

    path = tmp_path / "system-import.xlsx"
    path.write_bytes(_excel_bytes("Системный импорт", "999200002"))
    import_xlsx(session, path, original_filename="system-import.xlsx", audit_actor=AuditActor())
    system_event = session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "excel_import", AuditLog.entity_label.contains("system-import"))
    ).one()
    assert system_event.user_id is None
    registry = get_audit_registry(session, user="system", action="FILE_UPLOAD")
    assert any(row.id == system_event.id and row.employee == "Система" for row in registry.rows)
