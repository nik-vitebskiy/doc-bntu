from io import BytesIO
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select, text

from app.models import Contract, Organization, OrderItem, Specialty
from app.services.organization_service import canonical_faculty_name
from app.services.organization_service import registry
from app.services.organization_service import create_contract, save_item, update_contract
import pytest
from app.services.import_service import import_xlsx as _import_xlsx


def import_xlsx(*args, **kwargs):
    kwargs.setdefault("create_unknown_organizations", True)
    return _import_xlsx(*args, **kwargs)


def sample_workbook():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Организация-заказчик", "УНП", "Факультет", "Номер договора",
        "Полное наименование", "Адрес юридический", "Статус",
        "Дата начала договора", "Дата окончания договора",
        "Код специальности, направления специальности, специализации",
        "Квалификация", "2027", "2028",
    ])
    for index in range(60):
        sheet.append([
            'ОАО "МТЗ"', "100316761", f"Факультет {index % 11 + 1}", "№МТЗ-1 от 01.10.2020",
            "Минский тракторный завод", "Минск", "Активен",
            "01.10.2020", "31.12.2030", f"TEST-{index + 1:02d}",
            "Инженер", index + 1, index + 2,
        ])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _counts(session):
    return {
        table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("organization", "contract", "contract_faculty", "order_item", "annual_demand")
    }


def test_marketing_faculty_alias_uses_the_reference_name():
    assert canonical_faculty_name("Маркетинга, менеджмента и предпринимательства") == (
        "Маркетинга, менеджмента, предпринимательства"
    )


def test_import_creates_one_shared_contract_and_repeat_is_idempotent(session, user, tmp_path):
    path = tmp_path / "source.xlsx"
    path.write_bytes(sample_workbook())
    first = import_xlsx(session, path, user.id)
    assert (first.organizations, first.contracts, first.faculties, first.specialties) == (1, 1, 11, 60)
    assert (first.organizations_created, first.contracts_created, first.faculty_links_created, first.order_items_created) == (1, 1, 11, 60)
    assert _counts(session) == {
        "organization": 1, "contract": 1, "contract_faculty": 11,
        "order_item": 60, "annual_demand": 120,
    }
    contracts = session.scalars(select(Contract)).all()
    assert len(contracts[0].faculty_links) == 11
    assert {item.faculty_id for item in contracts[0].items} == {link.faculty_id for link in contracts[0].faculty_links}
    contract = contracts[0]
    contract.status = "Закрыт"
    session.commit()

    second = import_xlsx(session, path, user.id)
    assert second.rows_processed == 60
    assert (second.organizations_created, second.contracts_created, second.faculty_links_created, second.order_items_created) == (0, 0, 0, 0)
    assert (second.organizations_updated, second.contracts_updated, second.order_items_updated) == (1, 1, 60)
    assert _counts(session) == {
        "organization": 1, "contract": 1, "contract_faculty": 11,
        "order_item": 60, "annual_demand": 120,
    }
    assert session.get(Contract, contract.id).status == "Активен"


def test_registry_splits_shared_contract_by_faculty(session, user, tmp_path):
    path = tmp_path / "source.xlsx"
    path.write_bytes(sample_workbook())
    import_xlsx(session, path, user.id)

    rows, _, counts, _, total, _ = registry(session)
    assert (len(rows), total) == (11, 1)
    assert all(counts[f"Факультет {index}"] == 1 for index in range(1, 12))
    assert all(row.faculty_count == 11 for row in rows)
    assert sum(len(row.specialty_codes) for row in rows) == 60

    filtered, _, _, _, total, _ = registry(session, faculty="Факультет 1")
    assert len(filtered) == 1 and total == 1
    assert filtered[0].faculty.name == "Факультет 1"
    assert filtered[0].specialty_codes == [f"TEST-{number:02d}" for number in (1, 12, 23, 34, 45, 56)]
    by_code, _, _, _, _, _ = registry(session, query_text="TEST-12")
    assert [(row.faculty.name, row.contract.id) for row in by_code] == [("Факультет 1", filtered[0].contract.id)]


def test_same_specialty_in_two_faculties_is_not_collapsed(session, user, tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Организация-заказчик", "УНП", "Факультет", "Номер договора",
                  "Код специальности, направления специальности, специализации"])
    for faculty in ("Факультет А", "Факультет Б"):
        sheet.append(["Завод", "100316761", faculty, "№ОБЩ-1 от 01.01.2025", "CODE-01"])
    path = tmp_path / "shared.xlsx"
    workbook.save(path)
    result = import_xlsx(session, path, user.id)
    assert (result.contracts, result.order_items_created) == (1, 2)
    rows, _, _, _, count, _ = registry(session)
    assert count == 1
    assert {(row.faculty.name, tuple(row.specialty_codes)) for row in rows} == {
        ("Факультет А", ("CODE-01",)), ("Факультет Б", ("CODE-01",)),
    }


def test_import_without_optional_columns_preserves_existing_values(session, user, tmp_path):
    organization = Organization(
        unp="100316761", short_name="Завод", full_name="Полное название",
        legal_address="Минск", authority="Минпром", phone="123",
    )
    specialty = Specialty(code="CODE-OLD", name="CODE-OLD", qualification="Инженер")
    session.add_all([organization, specialty])
    session.flush()

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Организация-заказчик", "УНП", "Факультет", "Номер договора",
                  "Код специальности, направления специальности, специализации"])
    sheet.append(["Завод", "100316761", "Факультет А", "№Д-1 от 01.01.2025", "CODE-OLD"])
    sheet.append(["Завод", "100316761", "Факультет А", "№Д-1 от 01.01.2025", "CODE-NEW"])
    path = tmp_path / "without_optional_columns.xlsx"
    workbook.save(path)

    import_xlsx(session, path, user.id)

    assert organization.full_name == "Полное название"
    assert organization.legal_address == "Минск"
    assert organization.authority == "Минпром"
    assert organization.phone == "123"
    assert specialty.qualification == "Инженер"
    assert session.scalar(select(Specialty).where(Specialty.code == "CODE-NEW")).qualification is None
    old_item = session.scalar(select(OrderItem).where(OrderItem.specialty_id == specialty.id))
    assert old_item.qualification_value is None


def test_import_without_qualification_keeps_existing_order_item_value(session, user, tmp_path):
    path = tmp_path / "initial.xlsx"
    path.write_bytes(sample_workbook())
    import_xlsx(session, path, user.id)
    item = session.scalar(select(OrderItem).join(Specialty).where(Specialty.code == "TEST-01"))
    item.qualification_value = "Квалификация документа"
    session.flush()

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Организация-заказчик", "УНП", "Факультет", "Номер договора",
                  "Код специальности, направления специальности, специализации"])
    sheet.append(['ОАО "МТЗ"', "100316761", "Факультет 1", "№МТЗ-1 от 01.10.2020", "TEST-01"])
    workbook.save(path)

    import_xlsx(session, path, user.id)
    assert item.qualification_value == "Квалификация документа"


def test_qualification_migration_trims_values_and_normalizes_blanks(session, monkeypatch):
    trimmed = Specialty(code="TRIM-01", name="TRIM-01", qualification="  Инженер  ")
    blank = Specialty(code="TRIM-02", name="TRIM-02", qualification="   ")
    session.add_all([trimmed, blank])
    session.flush()
    migration_path = Path("alembic/versions/20260928_17_trim_specialty_qualifications.py")
    spec = spec_from_file_location("trim_specialty_qualifications", migration_path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration.op, "execute", lambda statement: session.execute(text(statement)))

    migration.upgrade()
    session.flush()
    session.expire_all()

    assert trimmed.qualification == "Инженер"
    assert blank.qualification is None


def test_cannot_remove_faculty_that_owns_order_lines(session, user):
    from app.models import Organization
    organization = Organization(unp="100316761", short_name="Завод", full_name="Завод")
    session.add(organization)
    session.flush()
    contract = create_contract(session, organization.id, ["Факультет А", "Факультет Б"], "ОБЩ-1", "2030-12-31")
    faculty = next(link.faculty for link in contract.faculty_links if link.faculty.name == "Факультет А")
    save_item(session, contract.id, "CODE-01", "Инженер", {"faculty_id": str(faculty.id)}, user_id=user.id)
    with pytest.raises(ValueError, match="Нельзя убрать факультет"):
        update_contract(session, contract, "ОБЩ-1", "2026-09-22", "2030-12-31", ["Факультет Б"])
    session.rollback()
