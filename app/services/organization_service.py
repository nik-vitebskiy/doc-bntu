from datetime import date, datetime, timezone

from sqlalchemy import extract, func, or_

from ..models import AdditionalAgreement, AnnualDemand, AppUser, Contract, ContractFaculty, Document, Faculty, Order, OrderItem, Organization, Specialty
from .audit_service import AuditAction, audited, current_audit_batch


def get_or_create_faculty(session, name):
    name = name.strip() or "Не указан"
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


def registry(session, query_text="", faculty="", end_year=""):
    query = session.query(Contract).join(Organization).join(ContractFaculty, ContractFaculty.contract_id == Contract.id).join(Faculty, Faculty.id == ContractFaculty.faculty_id).outerjoin(Order, Order.contract_id == Contract.id).outerjoin(OrderItem).outerjoin(Specialty)
    if query_text:
        query = query.filter(or_(Organization.short_name.ilike(f"%{query_text}%"), Contract.number.ilike(f"%{query_text}%"), Specialty.code.ilike(f"%{query_text}%")))
    if faculty:
        query = query.filter(Faculty.name == faculty)
    if end_year and end_year.isdigit():
        query = query.filter(extract("year", Contract.end_date) == int(end_year))
    contracts = query.distinct().order_by(Contract.id).all()
    faculties = [row[0] for row in session.query(Faculty.name).order_by(Faculty.name)]
    counts = dict(session.query(Faculty.name, func.count(ContractFaculty.contract_id)).join(ContractFaculty).group_by(Faculty.name).all())
    end_years = [row[0] for row in session.query(extract("year", Contract.end_date)).filter(Contract.end_date.is_not(None)).distinct().order_by(extract("year", Contract.end_date))]
    return contracts, faculties, counts, end_years


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
def create_contract(session, organization_id, faculties, number, end_date):
    names = faculties if isinstance(faculties, list) else [faculties]
    selected = [get_or_create_faculty(session, name) for name in names if name.strip()]
    if not selected:
        selected = [get_or_create_faculty(session, "Не указан")]
    contract = Contract(organization_id=organization_id, number=number or "Без номера", start_date=date.today(),
                        end_date=date.fromisoformat(end_date) if end_date else None,
                        status="Активен")
    session.add(contract)
    session.flush()
    for faculty in selected:
        session.add(ContractFaculty(contract_id=contract.id, faculty_id=faculty.id))
    return contract


@audited
def update_contract(session, contract: Contract, number: str, start_date: str, end_date: str):
    contract.number = number.strip() or "Без номера"
    contract.start_date = date.fromisoformat(start_date)
    contract.end_date = date.fromisoformat(end_date) if end_date else None
    return contract


@audited
def save_item(session, contract_id, specialty, qualification, form_data, item=None, user_id=None):
    values = {int(key.removeprefix("demand_")): int(value) if str(value).strip().isdigit() else 0
              for key, value in form_data.items() if key.startswith("demand_")}
    contract = session.get(Contract, contract_id)
    specialty_ref = get_or_create_specialty(session, specialty, qualification, ", ".join(contract.faculty_names))
    item = item or OrderItem(order_id=get_or_create_order(session, contract, user_id).id, specialty_id=specialty_ref.id)
    item.specialty_id = specialty_ref.id
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
def attach_scan(session, contract, filename, stored_name):
    document = Document(organization_id=contract.organization_id, contract_id=contract.id,
                        type="SIGNED_SCAN", status="SIGNED", file_id=stored_name,
                        original_filename=filename)
    session.add(document)
    return document


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
        item = OrderItem(order=copied, specialty_id=source_item.specialty_id,
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
            item.specialty: {
                "qualification": item.qualification,
                "profile": item.profile or "",
                "demand": {demand.year: demand.quantity for demand in item.annual_demands},
            }
            for item in order.items
        }

    before, after = values(previous), values(current)
    rows = []
    for specialty in sorted(set(before) | set(after)):
        old, new = before.get(specialty), after.get(specialty)
        if old is None:
            change = "Добавлено"
        elif new is None:
            change = "Исключено"
        elif old != new:
            change = "Изменено"
        else:
            change = "Без изменений"
        rows.append({"specialty": specialty, "before": old, "after": new, "change": change})
    return rows, years
