from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import Application, Order, OrderItem, Organization
from app.services.import_service import import_xlsx


def application_workbook(tmp_path):
    path = tmp_path / "applications.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Факультет", "Организация-заказчик", "Номер договора", "Статус",
        "Дата начала договора", "Дата окончания договора",
        "Код специальности, направления специальности, специализации ", 2026, 2027,
    ])
    sheet.append([None, 'Заявка ОАО "Альфа"', "A-1", "Заявка", "06.02.2024", "31.12.2028", "S-1", 1, 2])
    sheet.append(["Автотракторный", 'ОАО "Альфа"', "A-1", "Заявка", "06.02.2024", "31.12.2028", "S-2", 3, 4])
    sheet.append(["Автотракторный", 'ОАО "Альфа"', "A-2", "Заявка", "01.03.2024", None, "S-3", 5, 6])
    sheet.append(["Строительный", 'ООО "Бета"', "B-1", "Заявка", "02.04.2024", "31.12.2030", "S-4", 7, 8])
    workbook.save(path)
    return path


def test_imports_application_sample_with_blank_faculties(session, user, client, caplog, tmp_path):
    sample = application_workbook(tmp_path)
    result = import_xlsx(session, sample, user.id, original_filename="Заявки.xlsx")

    assert result.rows_processed == 4
    assert (result.organizations, result.applications, result.faculties, result.specialties) == (2, 3, 2, 4)
    assert result.applications_created == 3
    assert session.scalar(select(func.count()).select_from(OrderItem)) == 4
    assert session.scalar(select(func.count()).select_from(OrderItem).where(OrderItem.faculty_id.is_(None))) == 1
    assert all(not name.casefold().startswith("заявка ") for name in session.scalars(select(Organization.short_name)))
    assert session.scalar(select(Organization).where(Organization.short_name == 'ОАО "Альфа"'))
    application = session.scalar(
        select(Application).join(Organization).where(
            Organization.short_name == 'ОАО "Альфа"', Application.number == "A-1",
        )
    )
    assert application.signed_date.isoformat() == "2024-02-06"
    assert application.date_end.isoformat() == "2028-12-31"
    assert application.current_order.import_key == f"application:{application.id}"
    assert "не указан факультет" in caplog.text
    response = client.get(f"/applications/{application.id}")
    assert response.status_code == 200
    assert "Не указан" in response.text


def test_repeated_application_import_is_idempotent(session, user, tmp_path):
    sample = application_workbook(tmp_path)
    first = import_xlsx(session, sample, user.id)
    counts_before = (
        session.scalar(select(func.count()).select_from(Organization)),
        session.scalar(select(func.count()).select_from(Application)),
        session.scalar(select(func.count()).select_from(Order)),
        session.scalar(select(func.count()).select_from(OrderItem)),
    )

    second = import_xlsx(session, sample, user.id)
    counts_after = (
        session.scalar(select(func.count()).select_from(Organization)),
        session.scalar(select(func.count()).select_from(Application)),
        session.scalar(select(func.count()).select_from(Order)),
        session.scalar(select(func.count()).select_from(OrderItem)),
    )

    assert counts_after == counts_before
    assert first.rows_processed == second.rows_processed == 4
    assert (second.organizations_created, second.applications_created, second.order_items_created) == (0, 0, 0)
