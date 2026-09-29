"""Read-only reconciliation of AIS exports against signed current orders."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from io import BytesIO
import json
import logging
from pathlib import Path
import re
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import selectinload

from ..models import AnnualDemand, Application, Contract, Order, OrderItem, Organization
from .audit_service import AuditAction, audited, current_audit_batch
from .organization_service import canonical_faculty_name


logger = logging.getLogger(__name__)
REPORT_DIR = Path("data/reconciliation")


@dataclass(frozen=True)
class Difference:
    kind: str
    organization: str
    faculty: str
    specialty: str
    year: int
    ours: int
    ais: int
    note: str = ""


@dataclass(frozen=True)
class ReconciliationReport:
    token: str
    filename: str
    organizations_checked: int
    organizations_skipped: int
    skipped_names: list[str]
    differences: list[Difference]

    @property
    def differences_count(self):
        return len(self.differences)

    def sections(self):
        return {
            kind: [row for row in self.differences if row.kind == kind]
            for kind in ("changed", "ais_only", "system_only")
        }


def _text(value):
    return "" if value is None else str(value).strip()


def _organization_indexes(organizations):
    by_unp = {row.unp.strip(): row for row in organizations if row.unp and row.unp.strip()}
    by_name = {}
    for row in organizations:
        for value in (row.short_name, row.full_name):
            if value:
                by_name[value.strip().casefold()] = row
    return by_unp, by_name


def _current_values(session):
    values = defaultdict(int)
    orders = session.query(Order).filter_by(is_current=True).options(
        selectinload(Order.contract),
        selectinload(Order.additional_agreement),
        selectinload(Order.application),
        selectinload(Order.items).selectinload(OrderItem.faculty),
        selectinload(Order.items).selectinload(OrderItem.specialty_ref),
        selectinload(Order.items).selectinload(OrderItem.annual_demands),
    ).all()
    for order in orders:
        active = (
            (order.additional_agreement is not None and order.additional_agreement.status == "Активен")
            or (order.additional_agreement is None and order.contract is not None and order.contract.status == "Активен")
            or (order.application is not None and order.application.status == "Заявка")
        )
        if not active:
            continue
        for item in order.items:
            faculty = item.faculty.name if item.faculty else None
            for demand in item.annual_demands:
                values[(order.organization_id, faculty, item.specialty_ref.code, demand.year)] += demand.quantity
    return values


def _compare(ours, ais, organization_names):
    differences = []
    our_values = defaultdict(dict)
    ais_values = defaultdict(dict)
    for (org_id, faculty, code, year), quantity in ours.items():
        our_values[(org_id, faculty, code)][year] = quantity
    for (org_id, faculty, code, year), quantity in ais.items():
        ais_values[(org_id, faculty, code)][year] = quantity
    our_specialties = defaultdict(set)
    ais_specialties = defaultdict(set)
    for org_id, faculty, code in our_values:
        our_specialties[org_id].add((faculty, code))
    for org_id, faculty, code in ais_values:
        ais_specialties[org_id].add((faculty, code))

    for org_id in sorted(set(our_specialties) | set(ais_specialties)):
        consumed_ours = set()
        for faculty, code in sorted(ais_specialties[org_id], key=lambda row: ((row[0] or ""), row[1])):
            note = ""
            if faculty is None:
                matched = {(our_faculty, our_code) for our_faculty, our_code in our_specialties[org_id] if our_code == code}
                note = "Факультет в файле не указан; сопоставлено по коду"
            else:
                matched = {(faculty, code)} if (faculty, code) in our_specialties[org_id] else set()
            consumed_ours.update(matched)
            ais_year_values = ais_values[(org_id, faculty, code)]
            if not matched:
                for year, value in sorted(ais_year_values.items()):
                    if value:
                        differences.append(Difference("ais_only", organization_names[org_id], faculty or "Не указан", code, year, 0, value, note))
                continue
            our_years = set().union(*(our_values[(org_id, f, code)] for f, _code in matched))
            for year in sorted(set(ais_year_values) | our_years):
                our_value = sum(our_values[(org_id, f, code)].get(year, 0) for f, _code in matched)
                ais_value = ais_year_values.get(year, 0)
                if our_value != ais_value:
                    differences.append(Difference("changed", organization_names[org_id], faculty or "Не указан", code, year, our_value, ais_value, note))

        for faculty, code in sorted(our_specialties[org_id] - consumed_ours, key=lambda row: ((row[0] or ""), row[1])):
            for year, value in sorted(our_values[(org_id, faculty, code)].items()):
                if value:
                    differences.append(Difference("system_only", organization_names[org_id], faculty or "Не указан", code, year, value, 0))
    return differences


@audited
def reconcile_xlsx(session, path: Path, original_filename: str) -> ReconciliationReport:
    worksheet = load_workbook(path, data_only=True, read_only=True).active
    headers = [_text(cell.value) for cell in worksheet[1]]
    index = {header: position for position, header in enumerate(headers)}
    required = {"Организация-заказчик", "Код специальности, направления специальности, специализации"}
    missing = sorted(required - index.keys())
    if missing:
        raise ValueError(f"В Excel отсутствуют столбцы: {', '.join(missing)}")
    years = [(int(header), position) for position, header in enumerate(headers) if header.isdigit() and 2000 <= int(header) <= 2100]
    organizations = session.query(Organization).all()
    by_unp, by_name = _organization_indexes(organizations)
    organization_names = {row.id: row.short_name for row in organizations}
    ais = defaultdict(int)
    checked, skipped = set(), set()

    for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        raw_name = _text(row[index["Организация-заказчик"]])
        if not raw_name:
            continue
        normalized_name = re.sub(r"^\s*заявка\s+", "", raw_name, flags=re.IGNORECASE).strip()
        unp = _text(row[index["УНП"]]) if "УНП" in index else ""
        organization = by_unp.get(unp) if unp else None
        organization = organization or by_name.get(normalized_name.casefold())
        if organization is None:
            skipped.add(normalized_name)
            continue
        checked.add(organization.id)
        faculty = _text(row[index["Факультет"]]) if "Факультет" in index else ""
        faculty = canonical_faculty_name(faculty) or None
        code = _text(row[index["Код специальности, направления специальности, специализации"]])
        if not code:
            logger.warning("Строка %s сверки пропущена: нет кода специальности", row_number)
            continue
        for year, position in years:
            raw_value = row[position]
            try:
                quantity = int(raw_value or 0)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Строка {row_number}, год {year}: неверная потребность.") from error
            ais[(organization.id, faculty, code, year)] += quantity

    differences = _compare(_current_values(session), ais, organization_names)
    token = uuid4().hex
    report = ReconciliationReport(token, original_filename, len(checked), len(skipped), sorted(skipped), differences)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{token}.json").write_text(json.dumps({
        "token": token, "filename": original_filename,
        "organizations_checked": report.organizations_checked,
        "organizations_skipped": report.organizations_skipped,
        "skipped_names": report.skipped_names,
        "differences": [asdict(row) for row in differences],
    }, ensure_ascii=False), encoding="utf-8")
    current_audit_batch(session).record_values(
        AuditAction.FILE_UPLOAD, "ais_reconciliation", None,
        f"Сверка с АИС: {original_filename}, {len(differences)} расхождений, {len(checked)} организаций проверено",
        new={"filename": original_filename, "differences_count": len(differences), "organizations_checked": len(checked)},
    )
    return report


def load_report(token: str) -> ReconciliationReport:
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise FileNotFoundError
    data = json.loads((REPORT_DIR / f"{token}.json").read_text(encoding="utf-8"))
    return ReconciliationReport(
        data["token"], data["filename"], data["organizations_checked"], data["organizations_skipped"],
        data["skipped_names"], [Difference(**row) for row in data["differences"]],
    )


def report_xlsx(report: ReconciliationReport) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Расхождения"
    sheet.append(["Раздел", "Организация", "Факультет", "Код специальности", "Год", "У нас", "В АИС", "Примечание"])
    labels = {"changed": "Значения отличаются", "ais_only": "Есть в АИС, нет у нас", "system_only": "Есть у нас, нет в АИС"}
    for row in report.differences:
        sheet.append([labels[row.kind], row.organization, row.faculty, row.specialty, row.year, row.ours, row.ais, row.note])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream
