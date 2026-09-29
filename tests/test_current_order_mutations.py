from datetime import date

import pytest
from sqlalchemy import select

from app.models import Order, OrderItem
from app.services.organization_service import (
    InactiveOrderRevisionError,
    delete_item,
    register_additional_agreement,
    save_item,
)


def test_contract_order_mutations_use_current_revision_only(
    session, contract, user, actor
):
    original_item = save_item(
        session,
        contract.id,
        "CURRENT-01",
        "Инженер",
        {"demand_2027": "1"},
        user_id=user.id,
        audit_actor=actor,
    )
    original_order_id = original_item.order_id

    agreement = register_additional_agreement(
        session,
        contract,
        "ДС-CURRENT",
        date(2026, 9, 28),
        user.id,
        audit_actor=actor,
    )
    current_order = session.scalars(
        select(Order).where(Order.additional_agreement_id == agreement.id)
    ).one()
    original_count = len(session.get(Order, original_order_id).items)

    added = save_item(
        session,
        contract.id,
        "CURRENT-02",
        "Инженер",
        {"demand_2027": "2"},
        user_id=user.id,
        audit_actor=actor,
    )

    assert added.order_id == current_order.id
    assert added.order.is_current is True
    assert len(session.get(Order, original_order_id).items) == original_count

    save_item(
        session,
        contract.id,
        "CURRENT-02",
        "Инженер",
        {"faculty_id": str(added.faculty_id), "demand_2027": "7"},
        item=added,
        user_id=user.id,
        audit_actor=actor,
    )
    assert {row.year: row.quantity for row in added.annual_demands} == {2027: 7}

    added_id = added.id
    delete_item(session, added, audit_actor=actor)
    assert session.get(OrderItem, added_id) is None
    assert len(session.get(Order, original_order_id).items) == original_count


def test_replaced_revision_rejects_edit_delete_and_web_request(
    session, contract, user, actor, client
):
    old_item = save_item(
        session,
        contract.id,
        "CLOSED-01",
        "Инженер",
        {"demand_2027": "1"},
        user_id=user.id,
        audit_actor=actor,
    )
    register_additional_agreement(
        session,
        contract,
        "ДС-CLOSED",
        date(2026, 9, 28),
        user.id,
        audit_actor=actor,
    )

    with pytest.raises(InactiveOrderRevisionError, match="нельзя изменять"):
        save_item(
            session,
            contract.id,
            "CLOSED-01",
            "Инженер",
            {"faculty_id": str(old_item.faculty_id), "demand_2027": "8"},
            item=old_item,
            user_id=user.id,
            audit_actor=actor,
        )
    with pytest.raises(InactiveOrderRevisionError, match="нельзя изменять"):
        delete_item(session, old_item, audit_actor=actor)

    response = client.post(
        f"/items/{old_item.id}",
        data={
            "specialty": "CLOSED-01",
            "qualification": "Инженер",
            "faculty_id": str(old_item.faculty_id),
            "demand_2027": "8",
        },
    )
    assert response.status_code == 409
    assert "Заменённую редакцию" in response.json()["detail"]
    assert {row.year: row.quantity for row in old_item.annual_demands} == {2027: 1}
