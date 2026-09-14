from datetime import date

from sqlalchemy import func, or_

from ..models import AnnualDemand, AppUser, Contract, Document, Faculty, Order, OrderItem, Organization, Specialty


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


def get_or_create_order(session, contract):
    order = session.query(Order).filter_by(contract_id=contract.id).order_by(Order.id).first()
    if not order:
        order = Order(organization_id=contract.organization_id, contract_id=contract.id, created_by=demo_user(session).id)
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


def registry(session, query_text="", faculty=""):
    query = session.query(Contract).join(Organization).join(Faculty)
    if query_text:
        query = query.filter(or_(Organization.short_name.ilike(f"%{query_text}%"), Contract.number.ilike(f"%{query_text}%")))
    if faculty:
        query = query.filter(Faculty.name == faculty)
    contracts = query.order_by(Organization.short_name).all()
    faculties = [row[0] for row in session.query(Faculty.name).order_by(Faculty.name)]
    counts = dict(session.query(Faculty.name, func.count(Contract.id)).join(Contract).group_by(Faculty.name).all())
    return contracts, faculties, counts


def create_organization(session, **values):
    name = values["name"].strip()
    unp = values.get("unp") or f"9{(session.query(func.count(Organization.id)).scalar() + 1):08d}"
    org = Organization(unp=unp, short_name=name, full_name=values.get("full_name") or name,
                       legal_address=values.get("address") or None, authority=values.get("department") or None,
                       phone=values.get("phone") or None)
    session.add(org)
    session.commit()
    return org


def create_contract(session, organization_id, faculty, number, end_date):
    contract = Contract(organization_id=organization_id, faculty_id=get_or_create_faculty(session, faculty).id,
                        number=number or "Без номера", start_date=date.today(),
                        end_date=date.fromisoformat(end_date) if end_date else None)
    session.add(contract)
    session.commit()
    return contract


def save_item(session, contract_id, specialty, qualification, form_data, item=None):
    values = {int(key.removeprefix("demand_")): int(value) if str(value).strip().isdigit() else 0
              for key, value in form_data.items() if key.startswith("demand_")}
    contract = session.get(Contract, contract_id)
    specialty_ref = get_or_create_specialty(session, specialty, qualification, contract.faculty.name)
    item = item or OrderItem(order_id=get_or_create_order(session, contract).id, specialty_id=specialty_ref.id)
    item.specialty_id = specialty_ref.id
    for year, quantity in values.items():
        demand = next((row for row in item.annual_demands if row.year == year), None)
        if demand:
            demand.quantity = quantity
        else:
            item.annual_demands.append(AnnualDemand(year=year, quantity=quantity))
    session.add(item)
    session.commit()
    return item


def attach_scan(session, contract, filename, stored_name):
    session.add(Document(organization_id=contract.organization_id, contract_id=contract.id,
                         type="SIGNED_SCAN", status="SIGNED", file_id=stored_name))
    session.commit()
