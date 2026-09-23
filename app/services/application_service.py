from datetime import date

from ..models import AnnualDemand, Application, ApplicationFaculty, Order, OrderItem
from .audit_service import audited
from .organization_service import get_or_create_faculty, get_or_create_specialty


@audited
def create_application(session, organization_id, faculties, received_date, number, signed_date, user_id):
    selected = [get_or_create_faculty(session, name) for name in faculties if name.strip()]
    application = Application(organization_id=organization_id, received_date=date.fromisoformat(received_date),
                              number=number.strip() or None, signed_date=date.fromisoformat(signed_date) if signed_date else None,
                              status="Заявка", created_by=user_id)
    session.add(application); session.flush()
    for faculty in selected:
        session.add(ApplicationFaculty(application=application, faculty=faculty))
    session.add(Order(organization_id=organization_id, application_id=application.id, status="CURRENT", created_by=user_id, is_current=True))
    return application


@audited
def update_application(session, application, number, signed_date):
    application.number = number.strip() or None
    application.signed_date = date.fromisoformat(signed_date) if signed_date else None
    return application


@audited
def save_application_item(session, application, specialty, qualification, form_data, item=None):
    values = {int(key.removeprefix("demand_")): int(value) if str(value).strip().isdigit() else 0
              for key, value in form_data.items() if key.startswith("demand_")}
    specialty_ref = get_or_create_specialty(session, specialty, qualification, ", ".join(application.faculty_names))
    order = application.current_order
    item = item or OrderItem(order_id=order.id, specialty_id=specialty_ref.id)
    item.specialty_id = specialty_ref.id
    for year, quantity in values.items():
        demand = next((row for row in item.annual_demands if row.year == year), None)
        if demand: demand.quantity = quantity
        else: item.annual_demands.append(AnnualDemand(year=year, quantity=quantity))
    session.add(item)
    return item
