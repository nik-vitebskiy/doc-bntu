from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    AdditionalAgreement,
    AnnualDemand,
    AppUser,
    Application,
    AuditLog,
    Contract,
    ContractRedirect,
    Document,
    DocumentAttachment,
    Order,
    OrderItem,
    OrderRedirect,
    Organization,
)


PAGE_SIZE = 50
DISPLAY_TIMEZONE = ZoneInfo("Europe/Minsk")

ACTION_LABELS = {
    "CREATE": "Создано",
    "UPDATE": "Изменено",
    "DELETE": "Удалено",
    "STATUS_CHANGE": "Смена статуса",
    "FILE_UPLOAD": "Загружен файл",
    "FILE_DELETE": "Удалён файл",
    "FILE_RESTORE": "Восстановлен файл",
    "COPY": "Копирование заказа",
    "LOGIN": "Вход в систему",
    # Historical rows created before the unified action enum remain immutable,
    # but still need clear Russian labels in the registry.
    "ACTIVATE": "Активация доп. соглашения",
    "SEED_TEST_DATA": "Созданы тестовые данные",
}

ENTITY_FILTERS = {
    "organization": ("Организация", {"organization"}),
    "contract": ("Договор", {"contract"}),
    "additional_agreement": ("Доп. соглашение", {"additional_agreement"}),
    "application": ("Заявка", {"application"}),
    "order": ("Заказ", {"order", "order_item", "annual_demand", "specialty"}),
    "document": ("Файл", {"document", "document_attachment", "excel_import"}),
    "faculty": ("Факультет", {"faculty", "contract_faculty", "application_faculty"}),
    "app_user": ("Пользователь", {"app_user"}),
    "app_setting": ("Настройки", {"app_setting"}),
}

FIELD_LABELS = {
    "id": "Идентификатор",
    "organization_id": "Организация",
    "contract_id": "Договор",
    "application_id": "Заявка",
    "additional_agreement_id": "Доп. соглашение",
    "previous_agreement_id": "Предыдущее доп. соглашение",
    "previous_order_id": "Предыдущая редакция заказа",
    "order_id": "Заказ",
    "order_item_id": "Строка заказа",
    "specialty_id": "Специальность",
    "faculty_id": "Факультет",
    "created_by": "Создал",
    "updated_by": "Изменил",
    "number": "Номер",
    "name": "Наименование",
    "short_name": "Краткое наименование",
    "full_name": "Полное наименование",
    "unp": "УНП",
    "legal_address": "Юридический адрес",
    "authority": "Ведомство",
    "phone": "Телефон",
    "status": "Статус",
    "start_date": "Дата начала",
    "end_date": "Дата окончания",
    "date": "Дата",
    "received_date": "Дата получения",
    "signed_date": "Дата подписания",
    "activated_at": "Дата активации",
    "created_at": "Дата создания",
    "is_current": "Действующая редакция",
    "revision": "Редакция",
    "qualification": "Квалификация",
    "qualification_value": "Квалификация",
    "profile": "Профиль",
    "year": "Год",
    "quantity": "Потребность",
    "code": "Код",
    "type": "Тип документа",
    "version": "Версия",
    "file_id": "Сохранённый файл",
    "original_filename": "Имя файла",
    "filename": "Имя файла",
    "stored_name": "Сохранённый файл",
    "file_kind": "Назначение файла",
    "original_name": "Имя файла",
    "mime_type": "Формат файла",
    "size_bytes": "Размер, байт",
    "uploaded_by": "Загрузил",
    "uploaded_at": "Дата загрузки",
    "deleted_at": "Дата удаления",
    "rows_processed": "Обработано строк",
    "username": "Логин",
    "password": "Пароль",
    "role": "Роль",
    "is_active": "Активен",
    "must_change_password": "Требуется сменить пароль",
    "last_login_at": "Последний вход",
    "key": "Параметр",
    "value": "Значение",
    "description": "Описание",
    "source_order_id": "Исходный заказ",
    "target_order_id": "Новый заказ",
    "rows_count": "Скопировано строк",
}

VALUE_LABELS = {
    "ACTIVE": "Активен",
    "CLOSED": "Закрыт",
    "DRAFT": "Черновик",
    "CURRENT": "Действующий",
    "SIGNED": "Подписан",
    "SIGNED_SCAN": "Скан подписанного документа",
    "ADMIN": "Администратор",
    "HEAD": "Руководитель отдела",
    "SYSTEM": "Система",
}


@dataclass(frozen=True)
class AuditDiffLine:
    label: str
    old: str
    new: str


@dataclass
class AuditRow:
    id: int
    timestamp: datetime
    employee: str
    action: str
    action_label: str
    entity_type: str
    entity_label: str
    entity_url: str | None
    comment: str | None
    diff_lines: list[AuditDiffLine]
    copy_summary: str | None = None
    copied_items: list[str] | None = None
    file_url: str | None = None
    file_name: str | None = None


@dataclass
class AuditRegistry:
    rows: list[AuditRow]
    users: list[AppUser]
    total: int
    page: int
    pages: int


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, list):
        return ", ".join(_display_value(item) for item in value) or "—"
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_display_value(item)}" for key, item in value.items()) or "—"
    if isinstance(value, str):
        if value in VALUE_LABELS:
            return VALUE_LABELS[value]
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo:
                parsed = parsed.astimezone(DISPLAY_TIMEZONE)
            return parsed.strftime("%d.%m.%Y %H:%M") if "T" in value else parsed.strftime("%d.%m.%Y")
        except ValueError:
            return value
    return str(value)


def _field_label(entity_type: str, key: str) -> str:
    if entity_type == "app_user" and key == "full_name":
        return "ФИО"
    return FIELD_LABELS.get(key, key.replace("_", " ").capitalize())


def _diff_lines(entity_type: str, diff: dict[str, Any] | None) -> list[AuditDiffLine]:
    diff = diff or {}
    old = diff.get("old") or {}
    new = diff.get("new") or {}
    keys = [key for key in dict.fromkeys([*old.keys(), *new.keys()]) if key != "items"]
    return [
        AuditDiffLine(_field_label(entity_type, key), _display_value(old.get(key)), _display_value(new.get(key)))
        for key in keys
        if old.get(key) != new.get(key)
    ]


def _copied_items(diff: dict[str, Any] | None) -> tuple[str | None, list[str]]:
    new = (diff or {}).get("new") or {}
    items = new.get("items") or []
    rows_count = new.get("rows_count", len(items))
    if not items and rows_count is None:
        return None, []
    result = []
    for item in items:
        specialty = item.get("specialty") or "Специальность не указана"
        qualification = item.get("qualification")
        demands = item.get("demand") or []
        demand_text = ", ".join(f"{row.get('year')}: {row.get('quantity')}" for row in demands)
        details = "; ".join(part for part in (qualification, demand_text) if part)
        result.append(f"{specialty}{' — ' + details if details else ''}")
    return f"Скопировано строк заказа: {rows_count}", result


def _date_bounds(date_from: date | None, date_to: date | None) -> list[Any]:
    conditions: list[Any] = []
    if date_from:
        conditions.append(AuditLog.timestamp >= datetime.combine(date_from, time.min, DISPLAY_TIMEZONE))
    if date_to:
        conditions.append(AuditLog.timestamp < datetime.combine(date_to + timedelta(days=1), time.min, DISPLAY_TIMEZONE))
    return conditions


def _bulk_entity_urls(session: Session, records: list[AuditLog]) -> dict[tuple[str, int], str]:
    urls: dict[tuple[str, int], str] = {}
    by_type: dict[str, set[int]] = {}
    for record in records:
        if record.entity_id is not None and record.action != "DELETE":
            by_type.setdefault(record.entity_type, set()).add(record.entity_id)

    organization_ids = by_type.get("organization", set())
    if organization_ids:
        existing = set(session.scalars(select(Organization.id).where(Organization.id.in_(organization_ids))).all())
        for entity_id in existing:
            urls[("organization", entity_id)] = f"/organizations/{entity_id}"

    contract_ids = by_type.get("contract", set())
    if contract_ids:
        for contract_id, organization_id in session.execute(
            select(Contract.id, Contract.organization_id).where(Contract.id.in_(contract_ids))
        ):
            urls[("contract", contract_id)] = f"/organizations/{organization_id}?audit_highlight=contract-{contract_id}"
        missing = contract_ids - {entity_id for entity_type, entity_id in urls if entity_type == "contract"}
        if missing:
            for old_id, canonical_id, organization_id in session.execute(
                select(ContractRedirect.old_contract_id, Contract.id, Contract.organization_id)
                .join(Contract, Contract.id == ContractRedirect.contract_id)
                .where(ContractRedirect.old_contract_id.in_(missing))
            ):
                urls[("contract", old_id)] = f"/organizations/{organization_id}?audit_highlight=contract-{canonical_id}"

    agreement_ids = by_type.get("additional_agreement", set())
    if agreement_ids:
        for agreement_id, organization_id in session.execute(
            select(AdditionalAgreement.id, Contract.organization_id)
            .join(Contract, Contract.id == AdditionalAgreement.contract_id)
            .where(AdditionalAgreement.id.in_(agreement_ids))
        ):
            urls[("additional_agreement", agreement_id)] = f"/organizations/{organization_id}?audit_highlight=agreement-{agreement_id}"

    application_ids = by_type.get("application", set())
    if application_ids:
        for application_id in session.scalars(select(Application.id).where(Application.id.in_(application_ids))):
            urls[("application", application_id)] = f"/applications/{application_id}?audit_highlight=application-{application_id}"

    order_ids = by_type.get("order", set())
    if order_ids:
        for order in session.scalars(select(Order).where(Order.id.in_(order_ids))):
            url = _order_url(order)
            if url:
                urls[("order", order.id)] = url
        missing = order_ids - {entity_id for entity_type, entity_id in urls if entity_type == "order"}
        if missing:
            for old_id, order in session.execute(
                select(OrderRedirect.old_order_id, Order)
                .join(Order, Order.id == OrderRedirect.order_id)
                .where(OrderRedirect.old_order_id.in_(missing))
            ):
                url = _order_url(order)
                if url:
                    urls[("order", old_id)] = url

    item_ids = by_type.get("order_item", set())
    if item_ids:
        for item, order in session.execute(
            select(OrderItem, Order).join(Order, Order.id == OrderItem.order_id).where(OrderItem.id.in_(item_ids))
        ):
            url = _order_url(order, f"order-item-{item.id}")
            if url:
                urls[("order_item", item.id)] = url

    demand_ids = by_type.get("annual_demand", set())
    if demand_ids:
        query = (
            select(AnnualDemand.id, OrderItem.id, Order)
            .join(OrderItem, OrderItem.id == AnnualDemand.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(AnnualDemand.id.in_(demand_ids))
        )
        for demand_id, item_id, order in session.execute(query):
            url = _order_url(order, f"order-item-{item_id}")
            if url:
                urls[("annual_demand", demand_id)] = url

    attachment_ids = by_type.get("document_attachment", set())
    if attachment_ids:
        query = (
            select(DocumentAttachment.id, Document)
            .join(Document, Document.id == DocumentAttachment.document_id)
            .where(DocumentAttachment.id.in_(attachment_ids))
        )
        for attachment_id, document in session.execute(query):
            if document.application_id:
                url = f"/applications/{document.application_id}"
            elif document.additional_agreement_id:
                url = f"/additional-agreements/{document.additional_agreement_id}/comparison"
            else:
                url = f"/organizations/{document.organization_id}"
            urls[("document_attachment", attachment_id)] = url
    return urls


def _order_url(order: Order, anchor: str | None = None) -> str | None:
    suffix = f"#{anchor}" if anchor else ""
    if order.application_id:
        return f"/applications/{order.application_id}{suffix}"
    if order.contract_id:
        return f"/organizations/{order.organization_id}{suffix}"
    return None


def _file_details(record: AuditLog, attachments: dict[int, DocumentAttachment]) -> tuple[str | None, str | None]:
    diff = record.diff or {}
    values = (diff.get("old") if record.action == "FILE_DELETE" else diff.get("new")) or {}
    filename = values.get("original_name") or values.get("original_filename") or values.get("filename")
    attachment = attachments.get(record.entity_id) if record.entity_type == "document_attachment" and record.entity_id else None
    if attachment:
        filename = attachment.original_name
    if not filename:
        return None, None
    if attachment and attachment.deleted_at is None:
        return filename, f"/attachments/{attachment.id}/download"
    return filename, None


def get_audit_registry(
    session: Session,
    *,
    user: str = "",
    entity: str = "",
    action: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    query: str = "",
    page: int = 1,
) -> AuditRegistry:
    conditions: list[Any] = []
    if action:
        conditions.append(AuditLog.action == action)
    else:
        conditions.append(AuditLog.action != "LOGIN")
    if user == "system":
        conditions.append(AuditLog.user_id.is_(None))
    elif user.isdigit():
        conditions.append(AuditLog.user_id == int(user))
    if entity in ENTITY_FILTERS:
        conditions.append(AuditLog.entity_type.in_(ENTITY_FILTERS[entity][1]))
    conditions.extend(_date_bounds(date_from, date_to))
    if query.strip():
        pattern = f"%{query.strip()}%"
        conditions.append(or_(
            AuditLog.entity_label.ilike(pattern),
            AuditLog.comment.ilike(pattern),
            cast(AuditLog.diff, Text).ilike(pattern),
        ))

    base = select(AuditLog, AppUser.full_name, AppUser.username).outerjoin(AppUser, AppUser.id == AuditLog.user_id)
    if conditions:
        base = base.where(and_(*conditions))
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 1), pages)
    result = session.execute(
        base.order_by(
            AuditLog.timestamp.desc(),
            func.coalesce(AuditLog.parent_event_id, AuditLog.id).desc(),
            AuditLog.sequence.asc(),
            AuditLog.id.asc(),
        ).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    records = [entry[0] for entry in result]
    urls = _bulk_entity_urls(session, records)
    attachment_ids = {
        record.entity_id for record in records
        if record.entity_type == "document_attachment" and record.entity_id is not None
    }
    attachments = {
        attachment.id: attachment for attachment in session.scalars(
            select(DocumentAttachment).where(DocumentAttachment.id.in_(attachment_ids))
        )
    } if attachment_ids else {}
    rows: list[AuditRow] = []
    for record, full_name, username in result:
        copy_summary, copied_items = _copied_items(record.diff) if record.action == "COPY" else (None, [])
        file_name, file_url = _file_details(record, attachments) if record.action in {"FILE_UPLOAD", "FILE_DELETE", "FILE_RESTORE"} else (None, None)
        rows.append(AuditRow(
            id=record.id,
            timestamp=record.timestamp.astimezone(DISPLAY_TIMEZONE),
            employee=full_name or username or "Система",
            action=record.action,
            action_label=ACTION_LABELS.get(record.action, record.action),
            entity_type=record.entity_type,
            entity_label=record.entity_label,
            entity_url=urls.get((record.entity_type, record.entity_id)) if record.entity_id is not None else None,
            comment=record.comment,
            diff_lines=_diff_lines(record.entity_type, record.diff),
            copy_summary=copy_summary,
            copied_items=copied_items,
            file_url=file_url,
            file_name=file_name,
        ))
    users = session.scalars(select(AppUser).order_by(func.coalesce(AppUser.full_name, AppUser.username))).all()
    return AuditRegistry(rows=rows, users=list(users), total=total, page=page, pages=pages)
