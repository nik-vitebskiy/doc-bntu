from datetime import date, datetime

from openpyxl import load_workbook

from ..models import AnnualDemand, Contract, ContractFaculty, OrderItem, Organization
from .organization_service import get_or_create_faculty, get_or_create_order, get_or_create_specialty


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


def import_xlsx(path, session):
    """Import the legacy Excel export using contract_faculty as the source of truth."""
    worksheet = load_workbook(path, data_only=True).active
    headers = [text(cell.value) for cell in worksheet[1]]
    index = {header: i for i, header in enumerate(headers)}

    def field(row, label):
        return row[index[label]] if label in index else None

    years = [(int(header), i) for i, header in enumerate(headers) if header.isdigit() and 2000 <= int(header) <= 2100]
    count = 0
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        name = text(field(row, "Организация-заказчик"))
        if not name:
            continue
        unp = text(field(row, "УНП")) or f"9{count + 1:08d}"
        organization = session.query(Organization).filter_by(unp=unp).first()
        if not organization:
            organization = Organization(
                unp=unp, short_name=name, full_name=text(field(row, "Полное наименование")) or name,
                legal_address=text(field(row, "Адрес юридический")) or None,
                authority=text(field(row, "Ведомство")) or None, phone=text(field(row, "Телефоны")) or None,
            )
            session.add(organization)
            session.flush()
        faculty_name = text(field(row, "Факультет"))
        number = text(field(row, "Номер договора")) or "Без номера"
        faculty = get_or_create_faculty(session, faculty_name)
        contract = session.query(Contract).filter_by(organization_id=organization.id, number=number).first()
        if not contract:
            status = text(field(row, "Статус")) or "Активен"
            status = {"ACTIVE": "Активен", "CLOSED": "Закрыт"}.get(status, status)
            contract = Contract(organization_id=organization.id, number=number, status=status,
                                start_date=parse_date(field(row, "Дата начала договора")) or date.today(),
                                end_date=parse_date(field(row, "Дата окончания договора")))
            session.add(contract)
            session.flush()
        if not session.get(ContractFaculty, (contract.id, faculty.id)):
            session.add(ContractFaculty(contract_id=contract.id, faculty_id=faculty.id))
        specialty_code = text(field(row, "Код специальности, направления специальности, специализации"))
        if specialty_code:
            specialty = get_or_create_specialty(session, specialty_code, text(field(row, "Квалификация")), faculty_name)
            order = get_or_create_order(session, contract)
            item = session.query(OrderItem).filter_by(order_id=order.id, specialty_id=specialty.id).first()
            if not item:
                item = OrderItem(order_id=order.id, specialty_id=specialty.id)
                session.add(item)
                session.flush()
                for year, column in years:
                    session.add(AnnualDemand(order_item_id=item.id, year=year, quantity=int(row[column] or 0)))
        count += 1
    session.commit()
    return count
