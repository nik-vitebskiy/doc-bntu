from io import BytesIO

from openpyxl import Workbook
import pytest
from sqlalchemy import func, select

from app.models import Application, Contract, Organization
from app.services.import_service import import_xlsx


def import_file(tmp_path, application_mode):
    path = tmp_path / ("applications.xlsx" if application_mode else "contracts.xlsx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Организация-заказчик", "УНП", "Факультет", "Номер договора", "Статус",
        "Код специальности, направления специальности, специализации", 2027,
    ])
    for number in range(1, 6):
        document_number = f"A-{number}" if application_mode else f"№C-{number} от 01.01.2026"
        sheet.append([
            f"Организация {number}", f"10000000{number}", "Автотракторный", document_number,
            "Заявка" if application_mode else "Активен", f"S-{number}", number,
        ])
    workbook.save(path)
    return path


def add_known_organizations(session):
    session.add_all([
        Organization(unp=f"10000000{number}", short_name=f"Организация {number}", full_name=f"Организация {number}")
        for number in range(1, 4)
    ])
    session.flush()


@pytest.mark.parametrize("application_mode", [False, True])
def test_import_skips_unknown_organizations_unless_creation_is_enabled(session, user, tmp_path, application_mode):
    add_known_organizations(session)
    path = import_file(tmp_path, application_mode)
    model = Application if application_mode else Contract

    skipped = import_xlsx(session, path, user.id, create_unknown_organizations=False)
    assert session.scalar(select(func.count()).select_from(Organization)) == 3
    assert session.scalar(select(func.count()).select_from(model)) == 3
    assert (skipped.skipped_rows, skipped.skipped_organizations) == (2, 2)
    assert skipped.skipped_names == ("Организация 4", "Организация 5")
    assert "Пропущено: 2 строк (2 организаций)" in skipped.skipped_notice()

    created = import_xlsx(session, path, user.id, create_unknown_organizations=True)
    assert session.scalar(select(func.count()).select_from(Organization)) == 5
    assert session.scalar(select(func.count()).select_from(model)) == 5
    assert (created.organizations_created, created.skipped_rows) == (2, 0)

    repeated = import_xlsx(session, path, user.id, create_unknown_organizations=False)
    assert session.scalar(select(func.count()).select_from(model)) == 5
    assert (repeated.organizations_created, repeated.skipped_rows) == (0, 0)


def test_web_import_defaults_to_skip_and_exposes_opt_in(client, session, tmp_path):
    add_known_organizations(session)
    session.commit()
    path = import_file(tmp_path, False)
    data = path.read_bytes()
    response = client.post(
        "/import",
        files={"file": ("contracts.xlsx", BytesIO(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 303
    assert "import_notice=" in response.headers["location"]
    assert session.scalar(select(func.count()).select_from(Organization)) == 3

    response = client.post(
        "/import",
        data={"create_unknown_organizations": "true"},
        files={"file": ("contracts.xlsx", BytesIO(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 303
    assert session.scalar(select(func.count()).select_from(Organization)) == 5
    page = client.get("/")
    assert 'name="create_unknown_organizations"' in page.text
    assert "все организации республики" in page.text
