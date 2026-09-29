from datetime import date
from importlib.util import module_from_spec, spec_from_file_location

from openpyxl import Workbook
import pytest
from sqlalchemy import func, select

from app.models import (
    AdditionalAgreement, Contract, ContractFaculty, ContractRedirect, Document, Faculty,
    Order, OrderItem, OrderRedirect, Organization, Specialty,
)
from app.services.import_service import import_xlsx as _import_xlsx, parse_document_number
from app.services.organization_service import (
    InactiveOrderRevisionError, delete_item, register_additional_agreement, save_item,
)


HEADERS = [
    "Организация-заказчик", "УНП", "Факультет", "Номер договора", "Статус",
    "Код специальности, направления специальности, специализации", "Квалификация", "2027",
]


def import_xlsx(*args, **kwargs):
    kwargs.setdefault("create_unknown_organizations", True)
    return _import_xlsx(*args, **kwargs)


def write_workbook(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


@pytest.mark.parametrize(("raw", "base", "base_date", "agreement", "agreement_date"), [
    ("д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020", "221-АТФ/280", date(2020, 10, 1), "1", date(2025, 5, 6)),
    ("№535/6596 от 27.12.2023", "535/6596", date(2023, 12, 27), None, None),
    ("Доп соглаш №1 от 18.09.2024 №535/6596 от 27.12.2023", "535/6596", date(2023, 12, 27), "1", date(2024, 9, 18)),
    ("  №535/6596   от 27.12.2023 г. ", "535/6596", date(2023, 12, 27), None, None),
    ("доп. соглашение №2 от 1.9.2025 №A-1 от 2.1.2024", "A-1", date(2024, 1, 2), "2", date(2025, 9, 1)),
])
def test_parse_document_number(raw, base, base_date, agreement, agreement_date):
    parsed = parse_document_number(raw)
    assert (parsed.base_number, parsed.base_date) == (base, base_date)
    assert (parsed.agreement_number, parsed.agreement_date) == (agreement, agreement_date)


@pytest.mark.parametrize("raw", ["Без номера", "№A-1", "№A-1 от 31.02.2025"])
def test_parse_document_number_rejects_incomplete_or_invalid_values(raw):
    with pytest.raises(ValueError):
        parse_document_number(raw)


def test_invalid_document_date_is_logged_and_row_is_skipped(session, user, tmp_path, caplog):
    path = tmp_path / "invalid.xlsx"
    write_workbook(path, [["Завод", "123456789", "Автотракторный", "№A-1 от 31.02.2025", "Активен", "S-1", "Инженер", 1]])
    result = import_xlsx(session, path, user.id)
    assert result.rows_processed == 0
    assert session.scalar(select(func.count(Contract.id))) == 0
    assert "31.02.2025" in caplog.text and "Строка 2" in caplog.text


def test_import_builds_idempotent_contract_and_agreement_snapshots(session, user, actor, tmp_path):
    path = tmp_path / "maz.xlsx"
    contract_number = "№535/6596 от 27.12.2023"
    agreement_number = "Доп соглаш №1 от 18.09.2024 №535/6596 от 27.12.2023"
    rows = [
        ["ОАО МАЗ", "100000001", "Автотракторный", contract_number, "Активен", f"C-{index:02d}", "Инженер", index]
        for index in range(1, 37)
    ]
    rows.extend([
        ["ОАО МАЗ", "100000001", "Автотракторный", agreement_number, "Активен", f"A-{index:02d}", "Инженер", index]
        for index in range(1, 5)
    ])
    write_workbook(path, rows)

    import_xlsx(session, path, user.id)
    contract = session.scalar(select(Contract).where(Contract.number == "535/6596"))
    imported_orders = session.scalars(select(Order).where(Order.contract_id == contract.id)).all()
    assert len(imported_orders) == 2
    assert len(contract.items) == 40
    first_order_count = session.scalar(select(func.count(Order.id)))

    import_xlsx(session, path, user.id)
    assert session.scalar(select(func.count(Order.id))) == first_order_count

    agreement = contract.agreements[0]
    manual = register_additional_agreement(session, contract, "2", date(2025, 1, 1), user.id, audit_actor=actor)
    manual_order = session.scalar(select(Order).where(Order.additional_agreement_id == manual.id))
    assert manual_order.import_key is None and manual_order.is_current
    assert agreement.status == "Закрыт"

    import_xlsx(session, path, user.id)
    assert session.scalar(select(func.count(Order.id))) == first_order_count + 1
    assert manual_order.is_current is True
    assert all(not order.is_current for order in imported_orders)
    assert agreement.status == "Закрыт"


def test_status_is_majority_and_mixed_values_are_logged(session, user, tmp_path, caplog):
    path = tmp_path / "statuses.xlsx"
    write_workbook(path, [
        ["Завод", "100000005", "Автотракторный", "№A-4 от 1.1.2024", "Активен", "S-1", "Инженер", 1],
        ["Завод", "100000005", "Автотракторный", "№A-4 от 1.1.2024", "Активен", "S-2", "Инженер", 1],
        ["Завод", "100000005", "Автотракторный", "№A-4 от 1.1.2024", "Закрыт", "S-3", "Инженер", 1],
    ])
    import_xlsx(session, path, user.id)
    contract = session.scalar(select(Contract).where(Contract.number == "A-4"))
    assert contract.status == "Активен"
    assert "Разные статусы" in caplog.text


def test_later_active_document_wins_specialty_conflict(session, user, tmp_path):
    path = tmp_path / "conflict.xlsx"
    write_workbook(path, [
        ["Завод", "100000002", "Автотракторный", "№A-1 от 1.1.2024", "Активен", "S-1", "Инженер", 1],
        ["Завод", "100000002", "Автотракторный", "д.с. №1 от 2.2.2024 №A-1 от 1.1.2024", "Активен", "S-1", "Инженер новый", 9],
    ])
    import_xlsx(session, path, user.id)
    contract = session.scalar(select(Contract).where(Contract.number == "A-1"))
    assert len(contract.items) == 1
    assert contract.items[0].qualification_value == "Инженер новый"
    assert {row.year: row.quantity for row in contract.items[0].annual_demands} == {2027: 9}


def test_closed_imported_documents_are_historical_and_read_only(session, user, actor, tmp_path):
    path = tmp_path / "closed.xlsx"
    write_workbook(path, [
        ["Завод", "100000003", "Автотракторный", "№A-2 от 1.1.2024", "Закрыт", "S-1", "Инженер", 1],
        ["Завод", "100000003", "Автотракторный", "д.с. №1 от 2.2.2024 №A-2 от 1.1.2024", "Закрыт", "S-2", "Инженер", 2],
    ])
    import_xlsx(session, path, user.id)
    contract = session.scalar(select(Contract).where(Contract.number == "A-2"))
    orders = session.scalars(select(Order).where(Order.contract_id == contract.id)).all()
    assert contract.status == "Закрыт"
    assert contract.agreements[0].status == "Закрыт"
    assert not any(order.is_current for order in orders)
    assert sum(len(order.items) for order in orders) == 2
    with pytest.raises(InactiveOrderRevisionError):
        delete_item(session, orders[0].items[0], audit_actor=actor)


def test_imported_current_order_is_editable_and_repeat_import_overwrites_changes(session, user, actor, tmp_path):
    path = tmp_path / "editable.xlsx"
    write_workbook(path, [["Завод", "100000004", "Автотракторный", "№A-3 от 1.1.2024", "Активен", "S-1", "Инженер", 1]])
    import_xlsx(session, path, user.id)
    contract = session.scalar(select(Contract).where(Contract.number == "A-3"))
    source_item = contract.items[0]
    form_data = {"faculty_id": str(source_item.faculty_id), "demand_2027": "7"}
    save_item(session, contract.id, "S-1", "Изменено", form_data, item=source_item, user_id=user.id, audit_actor=actor)
    added = save_item(session, contract.id, "S-2", "Ручная", form_data, user_id=user.id, audit_actor=actor)
    assert added.order.import_key and added.order.is_current
    assert source_item.qualification == "Изменено"
    delete_item(session, source_item, audit_actor=actor)
    session.flush()
    assert {item.specialty for item in contract.items} == {"S-2"}

    import_xlsx(session, path, user.id)
    session.expire_all()
    contract = session.scalar(select(Contract).where(Contract.number == "A-3"))
    assert [item.specialty for item in contract.items] == ["S-1"]
    assert contract.items[0].qualification == "Инженер"
    assert {row.year: row.quantity for row in contract.items[0].annual_demands} == {2027: 1}


def test_mtz_migration_redirects_old_contract_and_order(session):
    organization = Organization(unp="100316761", short_name="ОАО МТЗ", full_name="ОАО МТЗ")
    faculty = Faculty(name="Факультет МТЗ")
    specialties = [Specialty(code=f"MTZ-{index:02d}", name=f"MTZ-{index:02d}") for index in range(60)]
    session.add_all([organization, faculty, *specialties])
    session.flush()
    old_contract = Contract(
        organization_id=organization.id,
        number="д.с. №1 от 06.05.2025 №221-АТФ/280 от 01.10.2020",
        start_date=date(2020, 10, 1), end_date=date(2030, 12, 31), status="Активен",
    )
    session.add(old_contract)
    session.flush()
    session.add(ContractFaculty(contract_id=old_contract.id, faculty_id=faculty.id))
    old_order = Order(organization_id=organization.id, contract_id=old_contract.id, is_current=True)
    session.add(old_order)
    session.flush()
    document = Document(organization_id=organization.id, contract_id=old_contract.id, type="CONTRACT")
    session.add(document)
    for specialty in specialties:
        session.add(OrderItem(order_id=old_order.id, faculty_id=faculty.id, specialty_id=specialty.id))
    session.flush()
    old_contract_id, old_order_id = old_contract.id, old_order.id

    migration_path = "alembic/versions/20260928_18_imported_document_snapshots.py"
    spec = spec_from_file_location("imported_document_snapshots", migration_path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration._migrate_mtz(session.connection())
    session.expire_all()

    redirect = session.get(ContractRedirect, old_contract_id)
    order_redirect = session.get(OrderRedirect, old_order_id)
    normalized = session.get(Contract, redirect.contract_id)
    assert normalized.number == "221-АТФ/280"
    assert normalized.agreements[0].number == "1"
    assert order_redirect.order_id == normalized.current_order.id
    assert len(normalized.items) == 60
    assert session.get(Document, document.id).contract_id == normalized.id
