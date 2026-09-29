from datetime import date

from ..models import AnnualDemand, Application, ApplicationFaculty, Order, OrderItem
from .audit_service import audited
from .organization_service import ensure_current_order, get_or_create_faculty, get_or_create_specialty, get_specialty_from_catalog


@audited
def create_application(session, organization_id, faculties, number, signed_date, date_end, user_id):
    selected = [get_or_create_faculty(session, name) for name in faculties if name.strip()]
    application = Application(
        organization_id=organization_id,
        number=number.strip() or None,
        signed_date=date.fromisoformat(signed_date) if signed_date else None,
        date_end=date.fromisoformat(date_end) if date_end else None,
        status="Заявка",
        created_by=user_id,
    )
    session.add(application); session.flush()
    for faculty in selected:
        session.add(ApplicationFaculty(application=application, faculty=faculty))
    session.add(Order(organization_id=organization_id, application_id=application.id, status="CURRENT", created_by=user_id, is_current=True))
    return application


@audited
def update_application(session, application, number, signed_date, date_end):
    application.number = number.strip() or None
    application.signed_date = date.fromisoformat(signed_date) if signed_date else None
    application.date_end = date.fromisoformat(date_end) if date_end else None
    return application


@audited
def save_application_item(session, application, specialty, qualification, form_data, item=None, catalog_only=False):
    values = {int(key.removeprefix("demand_")): int(value) if str(value).strip().isdigit() else 0
              for key, value in form_data.items() if key.startswith("demand_")}
    specialty_ref = (
        get_specialty_from_catalog(session, specialty)
        if catalog_only
        else get_or_create_specialty(session, specialty, qualification, ", ".join(application.faculty_names))
    )
    order = application.current_order
    if not order:
        raise ValueError("У заявки нет действующей редакции заказа.")
    if item:
        if item.order.application_id != application.id:
            raise ValueError("Строка заказа не относится к этой заявке.")
        ensure_current_order(item.order)
    else:
        item = OrderItem(order_id=order.id, specialty_id=specialty_ref.id)
    faculty_id = str(form_data.get("faculty_id", "")).strip()
    item.faculty_id = int(faculty_id) if faculty_id.isdigit() else None
    if item.faculty_id and not session.get(ApplicationFaculty, (application.id, item.faculty_id)):
        session.add(ApplicationFaculty(application_id=application.id, faculty_id=item.faculty_id))
    item.specialty_id = specialty_ref.id
    item.profile = str(form_data.get("profile", "")).strip() or None
    item.qualification_value = qualification.strip() or None
    for year, quantity in values.items():
        demand = next((row for row in item.annual_demands if row.year == year), None)
        if demand: demand.quantity = quantity
        else: item.annual_demands.append(AnnualDemand(year=year, quantity=quantity))
    session.add(item)
    return item
