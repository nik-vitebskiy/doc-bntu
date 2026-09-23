from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import AdditionalAgreement, Application, Contract, Order, OrderItem
from .organization_service import compare_orders


@dataclass(frozen=True)
class OrderRevision:
    order: Order
    number: int
    created_at: datetime
    origin_label: str
    origin_kind: str
    is_current: bool
    creator_name: str
    item_count: int


@dataclass(frozen=True)
class OrderTableRow:
    faculty: str
    specialty: str
    qualification: str
    profile: str
    demand: dict[int, int]


@dataclass(frozen=True)
class OrderHistory:
    document_type: str
    document_id: int
    title: str
    back_url: str
    revisions: list[OrderRevision]


def _order_query():
    return select(Order).options(
        joinedload(Order.creator),
        joinedload(Order.contract),
        joinedload(Order.application),
        joinedload(Order.additional_agreement),
        selectinload(Order.items).selectinload(OrderItem.specialty_ref),
        selectinload(Order.items).selectinload(OrderItem.faculty),
        selectinload(Order.items).selectinload(OrderItem.annual_demands),
    )


def _date_text(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "дата не указана"


def _revision(order: Order) -> OrderRevision:
    if order.additional_agreement:
        origin = f"Доп. соглашение №{order.additional_agreement.number} от {_date_text(order.additional_agreement.date)}"
        kind = "additional_agreement"
    elif order.application:
        number = order.application.number or "без номера"
        origin = f"Заявка №{number} от {_date_text(order.application.signed_date or order.application.received_date)}"
        kind = "application"
    elif order.contract:
        origin = f"Договор №{order.contract.number} от {_date_text(order.contract.start_date)}"
        kind = "contract"
    else:
        origin = "Исходный заказ"
        kind = "order"
    creator = order.creator
    creator_name = "Система" if not creator or creator.username == "demo" else (creator.full_name or creator.username)
    return OrderRevision(
        order=order,
        number=order.revision,
        created_at=order.created_at,
        origin_label=origin,
        origin_kind=kind,
        is_current=order.is_current,
        creator_name=creator_name,
        item_count=len(order.items),
    )


def get_order_history(session: Session, document_type: str, document_id: int) -> OrderHistory | None:
    """Return every revision for a contract/agreement/application from one entry point."""
    if document_type == "contract":
        contract = session.get(Contract, document_id)
        if not contract:
            return None
        statement = _order_query().where(Order.contract_id == contract.id)
        title = f"История заказа договора №{contract.number}"
        back_url = f"/organizations/{contract.organization_id}"
    elif document_type == "additional_agreement":
        agreement = session.get(AdditionalAgreement, document_id)
        if not agreement:
            return None
        statement = _order_query().where(Order.contract_id == agreement.contract_id)
        title = f"История заказа по д.с. №{agreement.number}"
        back_url = f"/additional-agreements/{agreement.id}/comparison"
    elif document_type == "application":
        application = session.get(Application, document_id)
        if not application:
            return None
        statement = _order_query().where(Order.application_id == application.id)
        title = f"История заказа заявки №{application.number or 'без номера'}"
        back_url = f"/applications/{application.id}"
    else:
        return None
    orders = session.scalars(statement).unique().all()
    revisions = sorted((_revision(order) for order in orders), key=lambda row: (not row.is_current, -row.number, -row.order.id))
    return OrderHistory(document_type, document_id, title, back_url, revisions)


def get_revision(history: OrderHistory, order_id: int | None) -> OrderRevision | None:
    if order_id is None:
        return history.revisions[0] if history.revisions else None
    return next((revision for revision in history.revisions if revision.order.id == order_id), None)


def order_table(order: Order) -> tuple[list[OrderTableRow], list[int]]:
    years = sorted({demand.year for item in order.items for demand in item.annual_demands})
    rows = [
        OrderTableRow(
            faculty=item.faculty.name if item.faculty else "—",
            specialty=item.specialty,
            qualification=item.qualification,
            profile=item.profile or "",
            demand={demand.year: demand.quantity for demand in item.annual_demands},
        )
        for item in sorted(order.items, key=lambda item: ((item.faculty.name if item.faculty else ""), item.specialty))
    ]
    return rows, years


def compare_revisions(session: Session, history: OrderHistory, first_id: int, second_id: int):
    first = get_revision(history, first_id)
    second = get_revision(history, second_id)
    if not first or not second or first.order.id == second.order.id:
        return None
    before, after = sorted((first, second), key=lambda row: (row.number, row.order.id))
    rows, years = compare_orders(session, before.order, after.order)
    return before, after, rows, years
