from datetime import date, datetime, timezone
from dataclasses import dataclass

from sqlalchemy import extract, func, or_
from sqlalchemy.orm import selectinload

from ..models import AdditionalAgreement, AnnualDemand, AppUser, Contract, ContractFaculty, Document, Faculty, Order, OrderItem, Organization, Specialty
from .audit_service import AuditAction, audited, current_audit_batch
from .status_service import ExpiryUrgency, URGENCY_BUCKETS, expiry_urgency


FACULTY_NAME_ALIASES = {
    "Маркетинга, менеджмента и предпринимательства": "Маркетинга, менеджмента, предпринимательства",
}


@dataclass(frozen=True)
class RegistryRow:
    contract: Contract
    faculty: Faculty
    specialty_codes: list[str]
    faculty_count: int
    expiry: ExpiryUrgency | None


def canonical_faculty_name(name: str) -> str:
    normalized = name.strip()
    return FACULTY_NAME_ALIASES.get(normalized, normalized)


def get_or_create_faculty(session, name):
    name = canonical_faculty_name(name) or "Не указан"
    faculty = session.query(Faculty).filter_by(name=name).first()
    if not faculty:
        faculty = Faculty(name=name)
        session.add(faculty)
        session.flush()
    return faculty


def demo_user(session):
    user = session.query(AppUser).filter_by(username="demo").first()
    if not user:
        user = AppUser(username="demo", password_hash="not-used-in-demo")
        session.add(user)
        session.flush()
    return user


def get_or_create_order(session, contract, user_id=None):
    order = session.query(Order).filter_by(contract_id=contract.id).order_by(Order.id).first()
    if not order:
        creator_id = user_id or demo_user(session).id
        order = Order(organization_id=contract.organization_id, contract_id=contract.id, created_by=creator_id)
        session.add(order)
        session.flush()
    return order


def get_or_create_specialty(session, code, qualification="", faculty=""):
    code = code.strip()[:50]
    specialty = session.query(Specialty).filter_by(code=code).first()
    if not specialty:
        specialty = Specialty(code=code, name=code[:255], qualification=qualification[:255] or None, faculty=faculty[:255] or None)
        session.add(specialty)
        session.flush()
    elif qualification and not specialty.qualification:
        specialty.qualification = qualification[:255]
    return specialty


def registry(session, query_text="", faculty="", end_year="", urgency=""):
    all_faculties = session.query(Faculty).order_by(Faculty.name).all()
    faculties = [row.name for row in all_faculties]
    faculty_by_id = {row.id: row for row in all_faculties}
    rows = []
    counts = {name: 0 for name in faculties}
    contracts = (session.query(Contract).options(
        selectinload(Contract.organization),
        selectinload(Contract.faculty_links).selectinload(ContractFaculty.faculty),
        selectinload(Contract.orders).selectinload(Order.items).selectinload(OrderItem.specialty_ref),
        selectinload(Contract.agreements).selectinload(AdditionalAgreement.documents).selectinload(Document.attachments),
        selectinload(Contract.documents).selectinload(Document.attachments),
    ).order_by(Contract.id).all())
    needle = query_text.casefold().strip()
    for contract in contracts:
        by_faculty = {}
        for item in contract.items:
            if item.faculty_id is not None:
                by_faculty.setdefault(item.faculty_id, []).append(item.specialty)
        # Keep manually registered contracts visible before their first order line.
        if not by_faculty:
            by_faculty = {link.faculty_id: [] for link in contract.faculty_links}
        for faculty_id, codes in by_faculty.items():
            if faculty_id in faculty_by_id:
                counts[faculty_by_id[faculty_id].name] += 1
        if end_year and end_year.isdigit() and (not contract.end_date or contract.end_date.year != int(end_year)):
            continue
        for faculty_id, codes in by_faculty.items():
            faculty_ref = faculty_by_id.get(faculty_id)
            if not faculty_ref or (faculty and faculty_ref.name != faculty):
                continue
            if needle and not (needle in contract.organization.name.casefold() or needle in contract.number.casefold()
                               or any(needle in code.casefold() for code in codes)):
                continue
            rows.append(RegistryRow(
                contract,
                faculty_ref,
                list(dict.fromkeys(codes)),
                len(by_faculty),
                expiry_urgency(contract.end_date),
            ))
    urgency_counts = {key: 0 for key, _label in URGENCY_BUCKETS}
    for row in rows:
        if row.expiry:
            urgency_counts[row.expiry.bucket] += 1
    valid_buckets = set(urgency_counts)
    selected_urgency = urgency if urgency in valid_buckets else ""
    if selected_urgency:
        rows = [row for row in rows if row.expiry and row.expiry.bucket == selected_urgency]
    if selected_urgency == "due_30":
        rows.sort(key=lambda row: (not row.expiry.overdue, row.faculty_count > 1 if faculty else False))
    elif faculty:
        rows.sort(key=lambda row: row.faculty_count > 1)
    end_years = [row[0] for row in session.query(extract("year", Contract.end_date)).filter(Contract.end_date.is_not(None)).distinct().order_by(extract("year", Contract.end_date))]
    return rows, faculties, counts, end_years, len(contracts), urgency_counts


def organization_contracts(organization, faculty_id=None):
    """Order an organization's contracts while preserving optional faculty context."""
    context_id = faculty_id if faculty_id is not None else None

    def sort_key(contract):
        belongs_to_context = context_id is not None and any(
            link.faculty_id == context_id for link in contract.faculty_links
        )
        only_this_faculty = belongs_to_context and len(contract.faculty_links) == 1
        return only_this_faculty, belongs_to_context, contract.start_date or date.min, contract.id

    return sorted(organization.contracts, key=sort_key, reverse=True)


@audited
def create_organization(session, **values):
    name = values["name"].strip()
    unp = values.get("unp") or f"9{(session.query(func.count(Organization.id)).scalar() + 1):08d}"
    org = Organization(unp=unp, short_name=name, full_name=values.get("full_name") or name,
                       legal_address=values.get("address") or None, authority=values.get("department") or None,
                       phone=values.get("phone") or None)
    session.add(org)
    return org


@audited
def update_organization(session, organization: Organization, **values):
    organization.short_name = values["name"].strip()
    organization.full_name = values.get("full_name", "").strip() or organization.short_name
    organization.legal_address = values.get("address", "").strip() or None
    organization.authority = values.get("department", "").strip() or None
    organization.phone = values.get("phone", "").strip() or None
    return organization


@audited
def delete_organization(session, organization: Organization):
    session.delete(organization)


@audited
def create_contract(session, organization_id, faculties, number, end_date):
    normalized_number = number.strip() or "Без номера"
    if session.query(Contract.id).filter_by(organization_id=organization_id, number=normalized_number).first():
        raise ValueError("Договор с таким номером у этой организации уже существует.")
    names = faculties if isinstance(faculties, list) else [faculties]
    selected = [get_or_create_faculty(session, name) for name in names if name.strip()]
    if not selected:
        selected = [get_or_create_faculty(session, "Не указан")]
    contract = Contract(organization_id=organization_id, number=normalized_number, start_date=date.today(),
                        end_date=date.fromisoformat(end_date) if end_date else None,
                        status="Активен")
    session.add(contract)
    session.flush()
    for faculty in selected:
        session.add(ContractFaculty(contract=contract, faculty=faculty))
    return contract


@audited
def update_contract(session, contract: Contract, number: str, start_date: str, end_date: str, faculties):
    normalized_number = number.strip() or "Без номера"
    if session.query(Contract.id).filter(Contract.organization_id == contract.organization_id,
                                          Contract.number == normalized_number, Contract.id != contract.id).first():
        raise ValueError("Договор с таким номером у этой организации уже существует.")
    contract.number = normalized_number
    contract.start_date = date.fromisoformat(start_date)
    contract.end_date = date.fromisoformat(end_date) if end_date else None
    names = {name.strip() for name in faculties if name.strip()}
    selected = session.query(Faculty).filter(Faculty.name.in_(names)).all()
    if len(selected) != len(names):
        raise ValueError("Выбран неизвестный факультет.")
    selected_ids = {faculty.id for faculty in selected}
    occupied = {item.faculty_id for item in contract.items if item.faculty_id is not None}
    if occupied - selected_ids:
        raise ValueError("Нельзя убрать факультет, пока в его заказе есть специальности.")
    existing = {link.faculty_id: link for link in contract.faculty_links}
    for faculty in selected:
        if faculty.id not in existing:
            session.add(ContractFaculty(contract=contract, faculty=faculty))
    for faculty_id, link in existing.items():
        if faculty_id not in selected_ids:
            session.delete(link)
    return contract


@audited
def save_item(session, contract_id, specialty, qualification, form_data, item=None, user_id=None):
    values = {int(key.removeprefix("demand_")): int(value) if str(value).strip().isdigit() else 0
              for key, value in form_data.items() if key.startswith("demand_")}
    contract = session.get(Contract, contract_id)
    allowed = {link.faculty_id for link in contract.faculty_links}
    default_faculty = next(iter(allowed)) if len(allowed) == 1 else 0
    faculty_id = int(form_data.get("faculty_id") or (item.faculty_id if item else 0) or default_faculty)
    if faculty_id not in allowed:
        raise ValueError("Выберите факультет из списка факультетов договора.")
    specialty_ref = get_or_create_specialty(session, specialty, qualification, ", ".join(contract.faculty_names))
    item = item or OrderItem(order_id=get_or_create_order(session, contract, user_id).id, specialty_id=specialty_ref.id)
    item.specialty_id = specialty_ref.id
    item.faculty_id = faculty_id
    for year, quantity in values.items():
        demand = next((row for row in item.annual_demands if row.year == year), None)
        if demand:
            demand.quantity = quantity
        else:
            item.annual_demands.append(AnnualDemand(year=year, quantity=quantity))
    session.add(item)
    return item


@audited
def delete_item(session, item: OrderItem):
    destination = {
        "organization_id": item.order.contract.organization_id if item.order.contract else None,
        "application_id": item.order.application_id,
    }
    for demand in list(item.annual_demands):
        session.delete(demand)
    session.delete(item)
    return destination


@audited
def register_additional_agreement(session, contract: Contract, number: str, agreement_date: date, user_id: int) -> AdditionalAgreement:
    """Copy the effective order, activate the new agreement and close its predecessor."""
    previous_agreement = session.query(AdditionalAgreement).filter_by(contract_id=contract.id, status="Активен").order_by(AdditionalAgreement.id.desc()).first()
    agreement = AdditionalAgreement(contract_id=contract.id, number=number, date=agreement_date, status="Активен",
                                    previous_agreement_id=previous_agreement.id if previous_agreement else None,
                                    activated_at=datetime.now(timezone.utc))
    session.add(agreement)
    batch = current_audit_batch(session)
    root_event = batch.record(
        agreement,
        AuditAction.CREATE,
        comment=f"Активация дополнительного соглашения №{number}",
    )
    session.flush()

    source_order = session.query(Order).filter_by(contract_id=contract.id, is_current=True).order_by(Order.revision.desc()).first()
    if not source_order:
        source_order = get_or_create_order(session, contract, user_id)

    copied = Order(organization_id=contract.organization_id, contract_id=contract.id, additional_agreement_id=agreement.id,
                   status="CURRENT", created_by=user_id, previous_order_id=source_order.id,
                   revision=source_order.revision + 1, is_current=True)
    session.add(copied)
    copied_entities = [copied]
    copied_items = []
    for source_item in source_order.items:
        item = OrderItem(order=copied, specialty_id=source_item.specialty_id, faculty_id=source_item.faculty_id,
                         qualification_value=source_item.qualification_value, profile=source_item.profile)
        session.add(item)
        copied_entities.append(item)
        demands = []
        for demand in source_item.annual_demands:
            cloned_demand = AnnualDemand(order_item=item, year=demand.year, quantity=demand.quantity)
            session.add(cloned_demand)
            copied_entities.append(cloned_demand)
            demands.append({"year": demand.year, "quantity": demand.quantity})
        copied_items.append({
            "specialty": source_item.specialty,
            "qualification": source_item.qualification,
            "demand": demands,
        })
    batch.record_copy(
        copied,
        source_order_id=source_order.id,
        items=copied_items,
        copied_entities=copied_entities,
        parent=root_event,
    )

    if previous_agreement:
        old_status = previous_agreement.status
        previous_agreement.status = "Закрыт"
        batch.record(
            previous_agreement,
            AuditAction.STATUS_CHANGE,
            old={"status": old_status},
            new={"status": "Закрыт"},
            comment=f"Активировано д.с. №{number}",
            parent=root_event,
        )
    else:
        old_status = contract.status
        contract.status = "Закрыт"
        batch.record(
            contract,
            AuditAction.STATUS_CHANGE,
            old={"status": old_status},
            new={"status": "Закрыт"},
            comment=f"Активировано д.с. №{number}",
            parent=root_event,
        )
    old_is_current = source_order.is_current
    source_order.is_current = False
    batch.record(
        source_order,
        AuditAction.UPDATE,
        old={"is_current": old_is_current},
        new={"is_current": False},
        comment=f"Создана редакция заказа для д.с. №{number}",
        parent=root_event,
    )
    return agreement


def compare_agreement_order(session, agreement: AdditionalAgreement):
    """Return a human-readable difference between an agreement's order and its predecessor."""
    current = next(iter(agreement.orders), None)
    if not current or not current.previous_order_id:
        return [], []
    previous = session.get(Order, current.previous_order_id)
    years = sorted({demand.year for order in (previous, current) for item in order.items for demand in item.annual_demands})

    def values(order):
        return {
            (item.faculty_id, item.specialty): {
                "qualification": item.qualification,
                "profile": item.profile or "",
                "demand": {demand.year: demand.quantity for demand in item.annual_demands},
            }
            for item in order.items
        }

    before, after = values(previous), values(current)
    rows = []
    for faculty_id, specialty in sorted(set(before) | set(after), key=lambda key: (key[0] or 0, key[1])):
        old, new = before.get((faculty_id, specialty)), after.get((faculty_id, specialty))
        if old is None:
            change = "Добавлено"
        elif new is None:
            change = "Исключено"
        elif old != new:
            change = "Изменено"
        else:
            change = "Без изменений"
        faculty_ref = session.get(Faculty, faculty_id) if faculty_id else None
        rows.append({"faculty": faculty_ref.name if faculty_ref else "—", "specialty": specialty, "before": old, "after": new, "change": change})
    return rows, years
