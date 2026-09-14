import json
from datetime import date
from sqlalchemy import func, or_
from ..models import Contract, OrderItem, Organization, Upload

def registry(session, query_text="", faculty=""):
    query = session.query(Contract).join(Organization)
    if query_text: query = query.filter(or_(Organization.name.ilike(f"%{query_text}%"), Contract.number.ilike(f"%{query_text}%")))
    if faculty: query = query.filter(Contract.faculty == faculty)
    contracts = query.order_by(Organization.name).all()
    faculties = [x[0] for x in session.query(Contract.faculty).distinct().order_by(Contract.faculty) if x[0]]
    counts = dict(session.query(Contract.faculty, func.count(Contract.id)).group_by(Contract.faculty).all())
    return contracts, faculties, counts

def create_organization(session, **values):
    org = Organization(**values); session.add(org); session.commit(); return org

def create_contract(session, organization_id, faculty, number, end_date):
    contract = Contract(organization_id=organization_id, faculty=faculty, number=number, end_date=date.fromisoformat(end_date) if end_date else None)
    session.add(contract); session.commit(); return contract

def save_item(session, contract_id, specialty, qualification, form_data, item=None):
    values = {key.removeprefix("demand_"): int(value) if str(value).strip().isdigit() else 0 for key, value in form_data.items() if key.startswith("demand_")}
    item = item or OrderItem(contract_id=contract_id)
    item.specialty, item.qualification, item.demand_json = specialty, qualification, json.dumps(values, ensure_ascii=False)
    session.add(item); session.commit(); return item

def attach_scan(session, contract, filename, stored_name):
    session.add(Upload(contract_id=contract.id, filename=filename, stored_name=stored_name)); session.commit()
