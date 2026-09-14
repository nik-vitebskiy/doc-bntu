"""One-time, idempotent transfer from the former demo tables to the normalized schema."""
import json
from datetime import date

from sqlalchemy import inspect, text

from ..models import AnnualDemand, Contract, Document, OrderItem, Organization
from ..services.organization_service import get_or_create_faculty, get_or_create_order, get_or_create_specialty


def _unp(old_id, name):
    if "МТЗ" in name.upper():
        return "100316761"
    return f"8{old_id:08d}"


def migrate_legacy_data(session):
    """Transfer records once; return counters. Source tables are deliberately retained."""
    tables = set(inspect(session.bind).get_table_names())
    if not {"organizations", "contracts", "order_items"}.issubset(tables):
        return {"organizations": 0, "contracts": 0, "items": 0, "documents": 0}

    counters = {"organizations": 0, "contracts": 0, "items": 0, "documents": 0}
    organization_ids = {}
    contract_ids = {}
    for row in session.execute(text("SELECT * FROM organizations ORDER BY id")).mappings():
        org = session.query(Organization).filter_by(unp=_unp(row["id"], row["name"])).first()
        if not org:
            org = Organization(unp=_unp(row["id"], row["name"]), short_name=row["name"],
                               full_name=row["full_name"] or row["name"], legal_address=row["address"] or None,
                               authority=row["department"] or None, phone=row["phones"] or None)
            session.add(org); session.flush(); counters["organizations"] += 1
        organization_ids[row["id"]] = org.id

    for row in session.execute(text("SELECT * FROM contracts ORDER BY id")).mappings():
        faculty = get_or_create_faculty(session, row["faculty"] or "Не указан")
        contract = session.query(Contract).filter_by(organization_id=organization_ids[row["organization_id"]], faculty_id=faculty.id,
                                                     number=row["number"] or "Без номера").first()
        if not contract:
            contract = Contract(organization_id=organization_ids[row["organization_id"]], faculty_id=faculty.id,
                                number=row["number"] or "Без номера", status=(row["status"] or "ACTIVE")[:30],
                                start_date=row["start_date"] or date.today(), end_date=row["end_date"])
            session.add(contract); session.flush(); counters["contracts"] += 1
        contract_ids[row["id"]] = contract.id

    for row in session.execute(text("SELECT * FROM order_items ORDER BY id")).mappings():
        contract = session.get(Contract, contract_ids[row["contract_id"]])
        specialty = get_or_create_specialty(session, row["specialty"] or "Не указан", row["qualification"] or "", contract.faculty.name)
        order = get_or_create_order(session, contract)
        item = session.query(OrderItem).filter_by(order_id=order.id, specialty_id=specialty.id).first()
        if not item:
            item = OrderItem(order_id=order.id, specialty_id=specialty.id)
            session.add(item); session.flush()
            for year, quantity in json.loads(row["demand_json"] or "{}").items():
                session.add(AnnualDemand(order_item_id=item.id, year=int(year), quantity=int(quantity or 0)))
            counters["items"] += 1

    if "uploads" in tables:
        for row in session.execute(text("SELECT * FROM uploads ORDER BY id")).mappings():
            contract_id = contract_ids[row["contract_id"]]
            exists = session.query(Document).filter_by(contract_id=contract_id, file_id=row["stored_name"]).first()
            if not exists:
                contract = session.get(Contract, contract_id)
                session.add(Document(organization_id=contract.organization_id, contract_id=contract_id,
                                     type="SIGNED_SCAN", status="SIGNED", file_id=row["stored_name"]))
                counters["documents"] += 1
    session.commit()
    return counters


def consolidate_duplicate_orders(session):
    """Merge accidental empty duplicate orders created during an early migration run."""
    duplicate_contract_ids = session.execute(text("""
        SELECT contract_id FROM orders
        WHERE contract_id IS NOT NULL
        GROUP BY contract_id HAVING count(*) > 1
    """)).scalars().all()
    removed = 0
    for contract_id in duplicate_contract_ids:
        orders = session.execute(text("SELECT id FROM orders WHERE contract_id = :contract_id ORDER BY id"),
                                 {"contract_id": contract_id}).scalars().all()
        primary_id, duplicate_ids = orders[0], orders[1:]
        for duplicate_id in duplicate_ids:
            session.execute(text("UPDATE order_item SET order_id = :primary_id WHERE order_id = :duplicate_id"),
                            {"primary_id": primary_id, "duplicate_id": duplicate_id})
            session.execute(text("DELETE FROM orders WHERE id = :duplicate_id"), {"duplicate_id": duplicate_id})
            removed += 1
    session.commit()
    return removed
