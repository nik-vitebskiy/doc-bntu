from io import BytesIO

from openpyxl import Workbook


YEARS = tuple(range(2026, 2037))


def _workbook(title: str, headers: list[str], rows: list[list[object]]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        width = min(60, max(len(str(cell.value or "")) for cell in column) + 2)
        sheet.column_dimensions[column[0].column_letter].width = width
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def _demands(item) -> list[object]:
    values = {row.year: row.quantity for row in item.annual_demands}
    return [values.get(year, "—") for year in YEARS]


def contracts_xlsx(registry, faculty: str | list[str] = "") -> BytesIO:
    selected_faculties = {faculty} if isinstance(faculty, str) and faculty else set(faculty)
    rows = []
    for entry in registry.rows:
        contract = entry.contract
        for item in contract.items:
            faculty_name = item.faculty.name if item.faculty else ""
            if selected_faculties and faculty_name not in selected_faculties:
                continue
            rows.append([
                faculty_name,
                contract.organization.name,
                f"№{contract.number or ''} от {contract.start_date.strftime('%d.%m.%Y')}",
                entry.effective_status,
                contract.start_date.strftime("%d.%m.%Y"),
                contract.end_date.strftime("%d.%m.%Y") if contract.end_date else "",
                item.specialty,
                item.qualification,
                item.profile or "",
                *_demands(item),
            ])
    return _workbook("Договоры", [
        "Факультет", "Организация", "Номер и дата договора", "Статус",
        "Дата начала", "Дата окончания", "Код специальности",
        "Квалификация", "Профилизация", *map(str, YEARS),
    ], rows)


def applications_xlsx(registry, faculty: str | list[str] = "") -> BytesIO:
    selected_faculties = {faculty} if isinstance(faculty, str) and faculty else set(faculty)
    rows = []
    for application in registry.rows:
        for item in application.items:
            faculty_name = item.faculty.name if item.faculty else ""
            if selected_faculties and faculty_name not in selected_faculties:
                continue
            rows.append([
                faculty_name,
                application.organization.name,
                application.number or "",
                application.status,
                application.signed_date.strftime("%d.%m.%Y") if application.signed_date else "",
                application.date_end.strftime("%d.%m.%Y") if application.date_end else "",
                item.specialty,
                item.qualification,
                item.profile or "",
                *_demands(item),
            ])
    return _workbook("Заявки", [
        "Факультет", "Организация", "Номер заявки", "Статус",
        "Дата подписания", "Действует до", "Код специальности",
        "Квалификация", "Профилизация", *map(str, YEARS),
    ], rows)
