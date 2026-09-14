from datetime import date, datetime

from openpyxl import load_workbook

from .models import AnnualDemand, Contract, OrderItem, Organization
from .services.organization_service import get_or_create_faculty, get_or_create_order, get_or_create_specialty


def text(value):
    return "" if value is None else str(value).strip()


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text(value), fmt).date()
        except ValueError:
            pass
    return None


def import_xlsx(path, db):
    ws = load_workbook(path, data_only=True).active
    headers = [text(cell.value) for cell in ws[1]]
    index = {header: i for i, header in enumerate(headers)}

    def field(row, label):
        return row[index[label]] if label in index else None

    years = [(int(header), i) for i, header in enumerate(headers) if header.isdigit() and 2000 <= int(header) <= 2100]
    count = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = text(field(row, "Организация-заказчик"))
        if not name:
            continue
        unp = text(field(row, "УНП")) or f"9{count + 1:08d}"
        org = db.query(Organization).filter_by(unp=unp).first()
        if not org:
            org = Organization(
                unp=unp,
                short_name=name,
                full_name=text(field(row, "Полное наименование")) or name,
                legal_address=text(field(row, "Адрес юридический")) or None,
                authority=text(field(row, "Ведомство")) or None,
                phone=text(field(row, "Телефоны")) or None,
            )
            db.add(org)
            db.flush()
        faculty_name, number = text(field(row, "Факультет")), text(field(row, "Номер договора"))
        faculty = get_or_create_faculty(db, faculty_name)
        contract = db.query(Contract).filter_by(
            organization_id=org.id, faculty_id=faculty.id, number=number or "Без номера"
        ).first()
        if not contract:
            contract = Contract(
                organization_id=org.id,
                faculty_id=faculty.id,
                number=number or "Без номера",
                status=text(field(row, "Статус")) or "ACTIVE",
                start_date=parse_date(field(row, "Дата начала договора")) or date.today(),
                end_date=parse_date(field(row, "Дата окончания договора")),
            )
            db.add(contract)
            db.flush()
        specialty_code = text(field(row, "Код специальности, направления специальности, специализации"))
        qualification = text(field(row, "Квалификация"))
        if specialty_code:
            specialty = get_or_create_specialty(db, specialty_code, qualification, faculty_name)
            order = get_or_create_order(db, contract)
            item = db.query(OrderItem).filter_by(order_id=order.id, specialty_id=specialty.id).first()
            if not item:
                item = OrderItem(order_id=order.id, specialty_id=specialty.id)
                db.add(item)
                db.flush()
                for year, column in years:
                    db.add(AnnualDemand(order_item_id=item.id, year=year, quantity=int(row[column] or 0)))
        count += 1
    db.commit()
    return count
