from datetime import datetime, timezone
from typing import Any

from ..models import AppSetting, Organization
from .audit_service import audited, current_audit_batch


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
