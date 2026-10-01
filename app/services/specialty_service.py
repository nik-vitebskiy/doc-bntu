from dataclasses import dataclass
from math import ceil

from sqlalchemy import func, or_

from ..models import OrderItem, Specialty
from .audit_service import AuditAction, audited, current_audit_batch


@dataclass(frozen=True)
class SpecialtyPage:
    items: list[Specialty]
    total: int
    page: int
    per_page: int = 50

    @property
    def pages(self) -> int:
        return max(1, ceil(self.total / self.per_page))


def specialty_registry(session, query: str = "", page: int = 1, per_page: int = 50) -> SpecialtyPage:
    query = query.strip()
    statement = session.query(Specialty)
    if query:
        pattern = f"%{query}%"
        statement = statement.filter(or_(Specialty.code.ilike(pattern), Specialty.name.ilike(pattern)))
    total = statement.with_entities(func.count(Specialty.id)).scalar() or 0
    page = max(1, min(page, max(1, ceil(total / per_page))))
    items = statement.order_by(Specialty.code, Specialty.id).offset((page - 1) * per_page).limit(per_page).all()
    return SpecialtyPage(items, total, page, per_page)


@audited
def update_specialty(session, specialty: Specialty, name: str, profile: str, qualification: str) -> Specialty:
    old_values = {
        "name": specialty.name,
        "profile": specialty.profile,
        "qualification": specialty.qualification,
    }
    specialty.name = name.strip() or specialty.code
    specialty.profile = profile.strip() or None
    specialty.qualification = qualification.strip() or None

    updated_items = []
    for item in session.query(OrderItem).filter(OrderItem.specialty_id == specialty.id):
        changed = False
        if specialty.profile and not (item.profile or "").strip():
            item.profile = specialty.profile
            changed = True
        if specialty.qualification and not (item.qualification_value or "").strip():
            item.qualification_value = specialty.qualification
            changed = True
        if changed:
            updated_items.append(item)

    new_values = {
        "name": specialty.name,
        "profile": specialty.profile,
        "qualification": specialty.qualification,
    }
    if old_values != new_values or updated_items:
        batch = current_audit_batch(session)
        batch.suppress(*updated_items)
        batch.record(
            specialty,
            AuditAction.UPDATE,
            old=old_values,
            new=new_values,
            comment=(f"Дозаполнение из справочника: специальность {specialty.code}, "
                     f"обновлено {len(updated_items)} строк"),
        )
    return specialty
