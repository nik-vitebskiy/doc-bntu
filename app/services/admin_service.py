from datetime import datetime, timezone
from typing import Any

from ..models import AppSetting, Organization
from .audit_service import audited, current_audit_batch


BNTU_SETTING_FIELDS = {
    "bntu.full_name": "Полное наименование",
    "bntu.signer_position": "Должность подписанта",
    "bntu.signer_name": "ФИО подписанта",
    "bntu.power_of_attorney_number": "Номер доверенности",
    "bntu.power_of_attorney_date": "Дата доверенности",
    "bntu.legal_address": "Юридический адрес",
    "bntu.unp": "УНП",
    "bntu.okpo": "ОКПО",
    "bntu.bank_account": "Расчётный счёт",
    "bntu.bank_name": "Банк",
    "bntu.bic": "БИК",
}


def get_bntu_requisites(session) -> dict[str, str]:
    rows = session.query(AppSetting).filter(AppSetting.key.in_(BNTU_SETTING_FIELDS)).all()
    values = {key.removeprefix("bntu."): "" for key in BNTU_SETTING_FIELDS}
    for row in rows:
        values[row.key.removeprefix("bntu.")] = str(row.value or "")
    return values


@audited
def update_bntu_requisites(session, values: dict[str, str]):
    actor_id = current_audit_batch(session).actor.user_id
    now = datetime.now(timezone.utc)
    for key, description in BNTU_SETTING_FIELDS.items():
        value = str(values.get(key.removeprefix("bntu."), "")).strip()
        setting = session.get(AppSetting, key)
        if setting is None:
            session.add(AppSetting(
                key=key,
                value=value,
                description=description,
                updated_by=actor_id,
            ))
        elif setting.value != value:
            setting.value = value
            setting.description = description
            setting.updated_at = now
            setting.updated_by = actor_id


@audited
def update_setting(session, key: str, value: Any, description: str | None = None):
    actor_id = current_audit_batch(session).actor.user_id
    setting = session.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value, description=description, updated_by=actor_id)
        session.add(setting)
    else:
        setting.value = value
        if description is not None:
            setting.description = description
        setting.updated_at = datetime.now(timezone.utc)
        setting.updated_by = actor_id
    return setting


@audited
def merge_organizations(session, source: Organization, target: Organization):
    """Reserved audited entry point for the future merge workflow.

    No records are changed until field-conflict and duplicate-contract rules are
    approved. Raising keeps both business data and audit rows rolled back.
    """
    raise NotImplementedError("Логика слияния организаций ещё не согласована.")
