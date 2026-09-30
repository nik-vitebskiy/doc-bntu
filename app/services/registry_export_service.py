from io import BytesIO

from openpyxl import Workbook


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


def contracts_xlsx(registry) -> BytesIO:
    rows = []
    for entry in registry.rows:
        contract = entry.contract
        rows.append([
            contract.organization.name,
            f"{contract.number or ''} от {contract.start_date.strftime('%d.%m.%Y')}",
            ", ".join(contract.faculty_names),
            entry.effective_status,
            contract.end_date.strftime("%d.%m.%Y") if contract.end_date else "",
            "Есть" if contract.has_signed_scan else "Нет",
            ", ".join(contract.specialty_codes),
        ])
    return _workbook("Договоры", [
        "Организация", "Номер и дата договора", "Факультеты", "Статус",
        "Дата окончания", "Скан подписанного", "Специальности",
    ], rows)


def applications_xlsx(registry) -> BytesIO:
    rows = []
    for application in registry.rows:
        rows.append([
            application.number or "",
            application.organization.name,
            application.date_end.strftime("%d.%m.%Y") if application.date_end else "",
            application.signed_date.strftime("%d.%m.%Y") if application.signed_date else "",
            ", ".join(application.faculty_names),
            application.status,
            "Есть" if application.has_signed_scan else "Нет",
            ", ".join(dict.fromkeys(item.specialty for item in application.items)),
        ])
    return _workbook("Заявки", [
        "Номер заявки", "Организация", "Действует до", "Дата подписания",
        "Факультеты", "Статус", "Скан подписанной заявки", "Специальности",
    ], rows)
