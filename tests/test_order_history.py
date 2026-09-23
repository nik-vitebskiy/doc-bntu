from datetime import date

from sqlalchemy import select

from app.models import Order
from app.services.application_service import create_application
from app.services.order_history_service import compare_revisions, get_order_history, get_revision, order_table
from app.services.organization_service import register_additional_agreement, save_item


def test_contract_chain_has_three_order_revisions_in_history(session, contract, user, actor):
    original_item = save_item(
        session,
        contract.id,
        "TEST-HISTORY",
        "Инженер",
        {"demand_2027": "2"},
        user_id=user.id,
        audit_actor=actor,
    )
    original_order_id = original_item.order_id

    first_agreement = register_additional_agreement(
        session, contract, "ДС-01", date(2026, 9, 21), user.id, audit_actor=actor
    )
    first_order = session.scalars(
        select(Order).where(Order.additional_agreement_id == first_agreement.id)
    ).one()
    first_item = first_order.items[0]
    save_item(
        session,
        contract.id,
        "TEST-HISTORY",
        "Инженер",
        {"demand_2027": "4"},
        item=first_item,
        user_id=user.id,
        audit_actor=actor,
    )

    second_agreement = register_additional_agreement(
        session, contract, "ДС-02", date(2026, 9, 22), user.id, audit_actor=actor
    )
    history = get_order_history(session, "contract", contract.id)

    assert history is not None
    assert [revision.number for revision in history.revisions] == [3, 2, 1]
    assert [revision.is_current for revision in history.revisions] == [True, False, False]
    assert history.revisions[0].origin_label.startswith("Доп. соглашение №ДС-02")
    assert history.revisions[1].origin_label.startswith("Доп. соглашение №ДС-01")
    assert history.revisions[2].origin_label.startswith("Договор №TEST-2026/01")
    assert [revision.item_count for revision in history.revisions] == [1, 1, 1]
    assert all(revision.creator_name == "Тестовый сотрудник" for revision in history.revisions)

    original = get_revision(history, original_order_id)
    current = history.revisions[0]
    assert original is not None
    comparison = compare_revisions(session, history, current.order.id, original.order.id)
    assert comparison is not None
    before, after, rows, years = comparison
    assert (before.number, after.number) == (1, 3)
    assert years == [2027]
    assert rows[0]["change"] == "Изменено"
    assert rows[0]["before"]["demand"] == {2027: 2}
    assert rows[0]["after"]["demand"] == {2027: 4}

    agreement_history = get_order_history(session, "additional_agreement", second_agreement.id)
    assert agreement_history is not None
    assert [revision.number for revision in agreement_history.revisions] == [3, 2, 1]


def test_imported_or_initial_order_is_shown_as_single_source_revision(session, organization, user, actor):
    application = create_application(
        session,
        organization.id,
        ["Тестовый факультет"],
        "2026-09-20",
        "З-01",
        "",
        user.id,
        audit_actor=actor,
    )

    history = get_order_history(session, "application", application.id)
    assert history is not None
    assert len(history.revisions) == 1
    assert history.revisions[0].number == 1
    assert history.revisions[0].is_current is True
    assert history.revisions[0].origin_label.startswith("Заявка №З-01")


def test_order_history_page_is_read_only_and_supports_comparison_and_audit_link(
    session, contract, user, actor, client
):
    item = save_item(
        session,
        contract.id,
        "TEST-PAGE",
        "Инженер",
        {"demand_2027": "1"},
        user_id=user.id,
        audit_actor=actor,
    )
    original_order_id = item.order_id
    agreement = register_additional_agreement(
        session, contract, "ДС-WEB", date(2026, 9, 23), user.id, audit_actor=actor
    )
    current_order = session.scalars(
        select(Order).where(Order.additional_agreement_id == agreement.id)
    ).one()

    response = client.get(
        f"/contracts/{contract.id}/order-history",
        params={"revision_id": current_order.id, "compare_to": original_order_id},
    )
    assert response.status_code == 200
    assert "Редакция 2" in response.text
    assert "Сравнение редакций 1 → 2" in response.text
    assert "TEST-PAGE" in response.text
    assert "/audit?entity=order" in response.text
    assert f"entity_id={current_order.id}" in response.text
    assert f'action="/items/{item.id}"' not in response.text

    audit_page = client.get("/audit", params={"entity": "order", "entity_id": current_order.id})
    assert audit_page.status_code == 200
    assert f'entity_id" value="{current_order.id}"' in audit_page.text


def test_revision_from_another_document_cannot_be_opened(session, contract, organization, user, actor, client):
    first_item = save_item(
        session,
        contract.id,
        "TEST-OWN",
        "Инженер",
        {"demand_2027": "1"},
        user_id=user.id,
        audit_actor=actor,
    )
    application = create_application(
        session,
        organization.id,
        ["Другой факультет"],
        "2026-09-20",
        "З-02",
        "",
        user.id,
        audit_actor=actor,
    )
    application_order = application.current_order

    response = client.get(
        f"/contracts/{contract.id}/order-history",
        params={"revision_id": application_order.id, "compare_to": first_item.order_id},
    )
    assert response.status_code == 404

    response = client.get(
        f"/contracts/{contract.id}/order-history",
        params={"revision_id": first_item.order_id, "compare_to": application_order.id},
    )
    assert response.status_code == 404


def test_order_table_keeps_faculty_and_demand_values(session, contract, user, actor):
    item = save_item(
        session,
        contract.id,
        "TEST-TABLE",
        "Инженер",
        {"demand_2027": "3", "demand_2028": "5"},
        user_id=user.id,
        audit_actor=actor,
    )
    rows, years = order_table(item.order)

    assert years == [2027, 2028]
    assert rows[0].faculty == "Тестовый факультет"
    assert rows[0].specialty == "TEST-TABLE"
    assert rows[0].demand == {2027: 3, 2028: 5}
