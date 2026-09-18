from ..models import AdditionalAgreement, Application, Contract
from .audit_service import AuditAction, audited, current_audit_batch
from .status_service import (
    APPLICATION_STATUSES,
    CONTRACT_STATUSES,
    STATUS_ACTIVE,
    STATUS_APPLICATION,
    STATUS_CLOSED,
)


class StatusTransitionError(ValueError):
    pass


def allowed_status_transitions(document_type: str, current_status: str, role: str) -> tuple[str, ...]:
    if document_type in {"contract", "additional_agreement"}:
        return tuple(status for status in CONTRACT_STATUSES if status != current_status)
    if document_type == "application":
        if current_status == STATUS_APPLICATION:
            return (STATUS_CLOSED,)
        if role == "ADMIN" and current_status == STATUS_CLOSED:
            return (STATUS_APPLICATION,)
    return ()


def _validate_comment(
    document_type: str,
    target_status: str,
    current_status: str,
    role: str,
    comment: str,
) -> str:
    value = comment.strip()
    reverse_application = current_status == STATUS_CLOSED and target_status == STATUS_APPLICATION
    if document_type != "contract" and target_status == STATUS_CLOSED and not value:
        raise StatusTransitionError("При закрытии документа необходимо указать комментарий.")
    if reverse_application and role == "ADMIN" and not value:
        raise StatusTransitionError("Для обратного перехода необходимо указать комментарий.")
    return value


def _change_status(session, document, document_type: str, target_status: str, role: str, comment: str):
    allowed = allowed_status_transitions(document_type, document.status, role)
    if target_status not in allowed:
        raise StatusTransitionError("Этот переход статуса недоступен.")
    comment = _validate_comment(document_type, target_status, document.status, role, comment)
    old_status = document.status
    document.status = target_status
    current_audit_batch(session).record(
        document,
        AuditAction.STATUS_CHANGE,
        old={"status": old_status},
        new={"status": target_status},
        comment=comment or None,
    )
    return document


@audited
def change_contract_status(session, contract: Contract, target_status: str, role: str, comment: str):
    if target_status == STATUS_CLOSED and contract.active_agreement:
        raise StatusTransitionError(
            f"Нельзя закрыть договор: действует дополнительное соглашение №{contract.active_agreement.number}."
        )
    return _change_status(session, contract, "contract", target_status, role, comment)


@audited
def change_agreement_status(session, agreement: AdditionalAgreement, target_status: str, role: str, comment: str):
    if target_status == STATUS_ACTIVE:
        other_active = next(
            (row for row in agreement.contract.agreements if row.id != agreement.id and row.status == STATUS_ACTIVE),
            None,
        )
        if other_active:
            raise StatusTransitionError(
                f"Нельзя активировать д.с.: уже действует дополнительное соглашение №{other_active.number}."
            )
    return _change_status(session, agreement, "additional_agreement", target_status, role, comment)


@audited
def change_application_status(session, application: Application, target_status: str, role: str, comment: str):
    if target_status not in APPLICATION_STATUSES:
        raise StatusTransitionError("Неизвестный статус заявки.")
    return _change_status(session, application, "application", target_status, role, comment)
