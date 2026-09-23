from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from functools import wraps
from typing import Any, Callable

from sqlalchemy import event as sqlalchemy_event, inspect
from sqlalchemy.orm import Session, object_session

from ..models import (
    AdditionalAgreement,
    AnnualDemand,
    AppSetting,
    AppUser,
    Application,
    ApplicationFaculty,
    AuditLog,
    Contract,
    ContractFaculty,
    Document,
    DocumentAttachment,
    Faculty,
    Order,
    OrderItem,
    Organization,
    Specialty,
)


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"
    FILE_UPLOAD = "FILE_UPLOAD"
    FILE_DELETE = "FILE_DELETE"
    FILE_RESTORE = "FILE_RESTORE"
    COPY = "COPY"
    LOGIN = "LOGIN"


@dataclass(frozen=True)
class AuditActor:
    user_id: int | None = None
    ip_address: str | None = None


@dataclass
class PendingAuditEvent:
    action: AuditAction
    entity: Any | None
    entity_type: str
    entity_id: int | None = None
    entity_label: str | None = None
    old: dict[str, Any] | None = None
    new: dict[str, Any] | None = None
    comment: str | None = None
    parent: "PendingAuditEvent | None" = None
    audit_row: AuditLog | None = field(default=None, init=False)


SENSITIVE_FIELDS = {"password_hash", "content"}
SENSITIVE_KEY_PARTS = ("password", "token", "secret", "api_key", "access_key", "private_key")
AUDIT_BATCH_KEY = "audit_batch"


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): "[СКРЫТО]" if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS) else _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def serialize_entity(entity: Any) -> dict[str, Any]:
    state = inspect(entity)
    result: dict[str, Any] = {}
    for attribute in state.mapper.column_attrs:
        key = attribute.key
        if key == "content":
            continue
        if key in SENSITIVE_FIELDS:
            if getattr(entity, key, None):
                result["password"] = "задан"
            continue
        result[key] = _json_value(getattr(entity, key, None))
    return result


def _order_label(order: Order | None) -> str:
    if not order:
        return "Заказ"
    if order.additional_agreement:
        return f"Заказ д.с. №{order.additional_agreement.number}"
    if order.application:
        return f"Заказ заявки №{order.application.number or order.application.id}"
    if order.contract:
        return f"Заказ договора №{order.contract.number}"
    return f"Заказ №{order.id}" if order.id else "Заказ"


def entity_label(entity: Any) -> str:
    try:
        if isinstance(entity, Organization):
            return f"Организация {entity.short_name}"
        if isinstance(entity, Contract):
            return f"Договор {entity.number}"
        if isinstance(entity, ContractFaculty):
            session = object_session(entity)
            faculty = entity.faculty or (session.get(Faculty, entity.faculty_id) if session else None)
            return faculty.name if faculty else f"Факультет {entity.faculty_id}"
        if isinstance(entity, AdditionalAgreement):
            return f"Доп. соглашение №{entity.number}"
        if isinstance(entity, Application):
            return f"Заявка {entity.number or 'без номера'}"
        if isinstance(entity, ApplicationFaculty):
            session = object_session(entity)
            faculty = entity.faculty or (session.get(Faculty, entity.faculty_id) if session else None)
            return faculty.name if faculty else f"Факультет {entity.faculty_id}"
        if isinstance(entity, Order):
            return _order_label(entity)
        if isinstance(entity, OrderItem):
            return f"{_order_label(entity.order)} → {entity.specialty}"
        if isinstance(entity, AnnualDemand):
            item = entity.order_item
            return f"{_order_label(item.order if item else None)} → {item.specialty if item else 'специальность'}"
        if isinstance(entity, Specialty):
            return f"Специальность {entity.code}"
        if isinstance(entity, Faculty):
            return f"Факультет {entity.name}"
        if isinstance(entity, AppUser):
            return f"Пользователь {entity.full_name or entity.username}"
        if isinstance(entity, AppSetting):
            return f"Настройка: {entity.description or entity.key}"
        if isinstance(entity, DocumentAttachment):
            return f"Файл {entity.original_name}"
        if isinstance(entity, Document):
            return f"Карточка документа {entity.id}"
    except Exception:
        # A deleted object's lazy relationship may no longer be available. The
        # fallback still leaves an immutable and identifiable audit record.
        pass
    entity_type = _entity_type(entity)
    identifier = _entity_identifier(entity)
    return f"{entity_type}/{identifier}" if identifier is not None else entity_type


def _entity_type(entity: Any) -> str:
    if isinstance(entity, (ContractFaculty, ApplicationFaculty)):
        return "faculty"
    value = getattr(entity, "__tablename__", entity.__class__.__name__.lower())
    return "order" if value == "orders" else value


def _entity_identifier(entity: Any) -> int | None:
    identifier = getattr(entity, "id", None)
    if identifier is not None:
        return identifier
    if isinstance(entity, (ContractFaculty, ApplicationFaculty)):
        return entity.faculty_id
    return None


class AuditBatch:
    """Collect domain changes and persist their audit rows atomically."""

    def __init__(
        self,
        session: Session,
        actor: AuditActor | None = None,
        comment: str | None = None,
    ):
        self.session = session
        self.actor = actor or AuditActor()
        self.comment = comment
        self.events: list[PendingAuditEvent] = []
        self._suppressed: set[int] = set()
        self._original: dict[int, dict[str, Any]] = {}

    def __enter__(self) -> "AuditBatch":
        if self.session.info.get(AUDIT_BATCH_KEY):
            raise RuntimeError("Nested audit batches must reuse the active batch")
        self.session.info[AUDIT_BATCH_KEY] = self
        sqlalchemy_event.listen(self.session, "before_flush", self._before_flush)
        sqlalchemy_event.listen(self.session, "loaded_as_persistent", self._remember_loaded)
        for entity in list(self.session.identity_map.values()):
            self._remember_loaded(self.session, entity)
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        try:
            if exc_type:
                self.session.rollback()
                return False
            self._collect_automatic_events()
            self.session.flush()
            self._persist_events()
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        finally:
            sqlalchemy_event.remove(self.session, "before_flush", self._before_flush)
            sqlalchemy_event.remove(self.session, "loaded_as_persistent", self._remember_loaded)
            self.session.info.pop(AUDIT_BATCH_KEY, None)
        return False

    def suppress(self, *entities: Any) -> None:
        self._suppressed.update(id(entity) for entity in entities)

    def record(
        self,
        entity: Any,
        action: AuditAction,
        *,
        old: dict[str, Any] | None = None,
        new: dict[str, Any] | None = None,
        comment: str | None = None,
        parent: PendingAuditEvent | None = None,
        label: str | None = None,
    ) -> PendingAuditEvent:
        event = PendingAuditEvent(
            action=action,
            entity=entity,
            entity_type=_entity_type(entity),
            entity_id=_entity_identifier(entity),
            entity_label=label,
            old=old,
            new=new,
            comment=comment if comment is not None else self.comment,
            parent=parent,
        )
        self.events.append(event)
        self.suppress(entity)
        return event

    def record_values(
        self,
        action: AuditAction,
        entity_type: str,
        entity_id: int | None,
        label: str,
        *,
        old: dict[str, Any] | None = None,
        new: dict[str, Any] | None = None,
        comment: str | None = None,
        parent: PendingAuditEvent | None = None,
    ) -> PendingAuditEvent:
        event = PendingAuditEvent(
            action=action,
            entity=None,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=label,
            old=old,
            new=new,
            comment=comment if comment is not None else self.comment,
            parent=parent,
        )
        self.events.append(event)
        return event

    def record_copy(
        self,
        target_order: Order,
        *,
        source_order_id: int,
        items: list[dict[str, Any]],
        copied_entities: list[Any],
        parent: PendingAuditEvent,
    ) -> PendingAuditEvent:
        # The target order is represented by one expandable COPY event. Its
        # mechanically cloned rows must never become individual CREATE events.
        self.suppress(*copied_entities)
        return self.record(
            target_order,
            AuditAction.COPY,
            old={"source_order_id": source_order_id},
            new={"target_order_id": target_order.id, "rows_count": len(items), "items": items},
            comment=f"Скопировано строк заказа: {len(items)}",
            parent=parent,
        )

    def _collect_automatic_events(self) -> None:
        new_entities = [entity for entity in self.session.new if self._should_collect(entity)]
        dirty_entities = [entity for entity in self.session.dirty if self._should_collect(entity)]
        deleted_entities = [entity for entity in self.session.deleted if self._should_collect(entity)]

        for entity in sorted(new_entities, key=self._sort_key):
            action = AuditAction.FILE_UPLOAD if isinstance(entity, DocumentAttachment) else AuditAction.CREATE
            self.events.append(
                PendingAuditEvent(action=action, entity=entity, entity_type=_entity_type(entity), comment=self.comment)
            )
            self.suppress(entity)

        for entity in sorted(dirty_entities, key=self._sort_key):
            changes = self._changed_columns(entity)
            if not changes:
                continue
            if "status" in changes:
                old_status, new_status = changes.pop("status")
                self.events.append(
                    PendingAuditEvent(
                        action=AuditAction.STATUS_CHANGE,
                        entity=entity,
                        entity_type=_entity_type(entity),
                        old={"status": old_status},
                        new={"status": new_status},
                        comment=self.comment,
                    )
                )
            if changes:
                self.events.append(
                    PendingAuditEvent(
                        action=AuditAction.UPDATE,
                        entity=entity,
                        entity_type=_entity_type(entity),
                        old={key: values[0] for key, values in changes.items()},
                        new={key: values[1] for key, values in changes.items()},
                        comment=self.comment,
                    )
                )
            self.suppress(entity)

        for entity in sorted(deleted_entities, key=self._sort_key):
            action = AuditAction.FILE_DELETE if isinstance(entity, DocumentAttachment) else AuditAction.DELETE
            self.events.append(
                PendingAuditEvent(
                    action=action,
                    entity=entity,
                    entity_type=_entity_type(entity),
                    entity_label=entity_label(entity),
                    old=serialize_entity(entity),
                    new={},
                    comment=self.comment,
                )
            )
            self.suppress(entity)

    def _before_flush(self, _session, _flush_context, _instances) -> None:
        # Capture SQLAlchemy history before flush clears it. This also covers
        # services that need intermediate flushes to obtain generated ids.
        self._collect_automatic_events()

    def _should_collect(self, entity: Any) -> bool:
        return not isinstance(entity, AuditLog) and id(entity) not in self._suppressed

    @staticmethod
    def _sort_key(entity: Any) -> tuple[str, int]:
        return _entity_type(entity), int(getattr(entity, "id", 0) or 0)

    def _changed_columns(self, entity: Any) -> dict[str, tuple[Any, Any]]:
        state = inspect(entity)
        changes: dict[str, tuple[Any, Any]] = {}
        original = self._original.get(id(entity), {})
        for attribute in state.mapper.column_attrs:
            key = attribute.key
            if isinstance(entity, AppSetting) and key in {"updated_at", "updated_by"}:
                continue
            history = state.attrs[key].history
            if not history.has_changes():
                continue
            if key in SENSITIVE_FIELDS:
                changes["password"] = ("скрыт", "изменён")
                continue
            old = _json_value(history.deleted[0]) if history.deleted else original.get(key)
            new = _json_value(history.added[-1]) if history.added else _json_value(getattr(entity, key, None))
            if old != new:
                changes[key] = (old, new)
        return changes

    def _remember_loaded(self, _session, entity: Any) -> None:
        if isinstance(entity, AuditLog) or id(entity) in self._original:
            return
        self._original[id(entity)] = serialize_entity(entity)

    def _persist_events(self) -> None:
        for sequence, event in enumerate(self.events, start=1):
            if event.entity is not None:
                event.entity_id = _entity_identifier(event.entity) or event.entity_id
                event.entity_label = event.entity_label or entity_label(event.entity)
                if event.action in {AuditAction.CREATE, AuditAction.FILE_UPLOAD} and event.new is None:
                    event.old = {}
                    event.new = serialize_entity(event.entity)
                if event.action == AuditAction.COPY and event.new and event.new.get("target_order_id") is None:
                    event.new["target_order_id"] = event.entity_id

            parent_id = None
            if event.parent:
                if not event.parent.audit_row:
                    raise RuntimeError("A parent audit event must precede its child")
                # Flush the pending parent only when a child needs its id.
                # Independent import events can be inserted in one batch.
                if event.parent.audit_row.id is None:
                    self.session.flush()
                parent_id = event.parent.audit_row.id

            row = AuditLog(
                user_id=self.actor.user_id,
                action=event.action.value,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                entity_label=event.entity_label or f"{event.entity_type}/{event.entity_id}",
                diff={"old": event.old or {}, "new": event.new or {}},
                comment=event.comment,
                ip_address=self.actor.ip_address,
                parent_event_id=parent_id,
                sequence=sequence,
            )
            self.session.add(row)
            event.audit_row = row
        self.session.flush()


def current_audit_batch(session: Session) -> AuditBatch:
    batch = session.info.get(AUDIT_BATCH_KEY)
    if not batch:
        raise RuntimeError("The operation is not running inside an audit batch")
    return batch


def audited(function: Callable):
    """Run a service mutation and its audit events in one transaction.

    Decorated services accept the infrastructure-only keyword arguments
    ``audit_actor`` and ``audit_comment``; they are not passed to the wrapped
    business function.
    """

    @wraps(function)
    def wrapper(session: Session, *args, **kwargs):
        actor = kwargs.pop("audit_actor", None)
        comment = kwargs.pop("audit_comment", None)
        active = session.info.get(AUDIT_BATCH_KEY)
        if active:
            return function(session, *args, **kwargs)
        with AuditBatch(session, actor=actor, comment=comment):
            return function(session, *args, **kwargs)

    return wrapper


def audit_login_enabled(session: Session) -> bool:
    setting = session.get(AppSetting, "audit_login_enabled")
    return True if setting is None else bool(setting.value)
