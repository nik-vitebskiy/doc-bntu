STATUS_ACTIVE = "Активен"
STATUS_APPLICATION = "Заявка"
STATUS_CLOSED = "Закрыт"

CONTRACT_STATUSES = (STATUS_ACTIVE, STATUS_CLOSED)
APPLICATION_STATUSES = (STATUS_APPLICATION, STATUS_CLOSED)

STATUS_CLASSES = {
    STATUS_ACTIVE: "status-active",
    STATUS_APPLICATION: "status-active",
    STATUS_CLOSED: "status-closed",
}

ORDER_CHANGE_CLASSES = {
    "Добавлено": "change-added",
    "Изменено": "change-updated",
    "Без изменений": "change-unchanged",
    "Исключено": "change-removed",
}

LEGACY_STATUS_LABELS = {"ACTIVE": STATUS_ACTIVE, "CLOSED": STATUS_CLOSED}


def status_label(value: str | None) -> str:
    return LEGACY_STATUS_LABELS.get(value or "", value or "—")


def status_class(value: str | None) -> str:
    return STATUS_CLASSES.get(status_label(value), "status-closed")


def order_change_class(value: str | None) -> str:
    return ORDER_CHANGE_CLASSES.get(value or "", "change-unchanged")
