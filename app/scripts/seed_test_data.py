"""Create an isolated dataset for manual testing; safe to run more than once."""
from datetime import date

from sqlalchemy import text

from app.models import AnnualDemand, AppUser, Contract, Order, OrderItem, Organization, SessionLocal
from app.services.auth_service import write_audit
from app.services.organization_service import get_or_create_faculty, get_or_create_specialty, register_additional_agreement


def main():
    session = SessionLocal()
    try:
        if session.query(Organization).filter_by(unp="000000001").first():
            print("Test data already exists")
            return
        admin = session.query(AppUser).filter_by(username="admin").one()
        organization = Organization(unp="000000001", short_name="ТЕСТ — Организация-заказчик",
                                    full_name="Тестовая организация для проверки функций",
                                    legal_address="г. Минск, тестовый адрес", authority="Тестовое ведомство",
                                    phone="+375 00 000-00-00")
        session.add(organization)
        session.flush()
        first_faculty = get_or_create_faculty(session, "Тестовый факультет А")
        second_faculty = get_or_create_faculty(session, "Тестовый факультет Б")
        contract = Contract(organization_id=organization.id, number="ТЕСТ-2026/01",
                            start_date=date(2026, 1, 1), end_date=date(2030, 12, 31), status="Активен")
        session.add(contract)
        session.flush()
        for faculty in (first_faculty, second_faculty):
            session.execute(text("INSERT INTO contract_faculty(contract_id, faculty_id) VALUES (:contract_id, :faculty_id) ON CONFLICT DO NOTHING"),
                            {"contract_id": contract.id, "faculty_id": faculty.id})
        source_order = Order(organization_id=organization.id, contract_id=contract.id, status="CURRENT",
                             created_by=admin.id, is_current=True, revision=1)
        session.add(source_order)
        session.flush()
        source_rows = [
            ("TEST-01", "Тестовый инженер", "Профиль А", {2027: 2, 2028: 3, 2029: 4}),
            ("TEST-02", "Тестовый аналитик", "Профиль Б", {2027: 1, 2028: 1, 2029: 2}),
            ("TEST-03", "Тестовый технолог", "", {2027: 5, 2028: 5, 2029: 5}),
        ]
        for code, qualification, profile, demand in source_rows:
            specialty = get_or_create_specialty(session, code, qualification, first_faculty.name)
            item = OrderItem(order_id=source_order.id, specialty_id=specialty.id, qualification_value=qualification, profile=profile)
            session.add(item)
            session.flush()
            for year, quantity in demand.items():
                session.add(AnnualDemand(order_item_id=item.id, year=year, quantity=quantity))
        session.commit()

        agreement = register_additional_agreement(session, contract, "ТЕСТ-ДС-2026/01", date(2026, 9, 16), admin.id)
        active_order = agreement.orders[0]
        changed = next(item for item in active_order.items if item.specialty == "TEST-01")
        next(demand for demand in changed.annual_demands if demand.year == 2028).quantity = 9
        session.delete(next(item for item in active_order.items if item.specialty == "TEST-02"))
        specialty = get_or_create_specialty(session, "TEST-04", "Тестовый проектировщик", second_faculty.name)
        added = OrderItem(order_id=active_order.id, specialty_id=specialty.id,
                          qualification_value="Тестовый проектировщик", profile="Профиль В")
        session.add(added)
        session.flush()
        for year, quantity in {2027: 3, 2028: 4, 2029: 6}.items():
            session.add(AnnualDemand(order_item_id=added.id, year=year, quantity=quantity))
        session.commit()
        write_audit(session, admin.id, "SEED_TEST_DATA", "organization", organization.id, "Тестовый договор и д.с.")
        print(f"Created test organization={organization.id}, contract={contract.id}, agreement={agreement.id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
