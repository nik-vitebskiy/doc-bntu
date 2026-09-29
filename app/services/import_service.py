"""Importer for manually uploaded heterogeneous Excel exports."""

from collections import Counter
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime
from hashlib import sha256
import logging
from pathlib import Path
import re

from openpyxl import load_workbook
from sqlalchemy import func

from ..models import AdditionalAgreement, AnnualDemand, Contract, ContractFaculty, Order, OrderItem, Organization
from .audit_service import AuditAction, audited, current_audit_batch
from .organization_service import get_or_create_faculty, get_or_create_specialty


logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(
    r"№\s*(?P<number>[^\s]+)\s+от\s+(?P<date>\d{1,2}\.\d{1,2}\.\d{4})(?:\s*г\.)?",
    re.IGNORECASE,
)
AGREEMENT_MARKER_RE = re.compile(
    r"(?:д\.\s*с\.|доп(?:\.|олнительное)?\s*соглаш(?:ение)?|допсоглашение|доп\.соглашение)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedDocumentNumber:
    base_number: str
    base_date: date
    agreement_number: str | None = None
    agreement_date: date | None = None


@dataclass(frozen=True)
class ImportResult:
    rows_processed: int
    organizations: int
    contracts: int
    faculties: int
    specialties: int
    organizations_created: int
    contracts_created: int
    faculty_links_created: int
    order_items_created: int

    def log_line(self, source: str) -> str:
        return (
            f"Импорт {source}: загружено {self.contracts} договоров, "
            f"{self.organizations} организаций, {self.faculties} факультетов, "
            f"{self.specialties} специальностей из {self.rows_processed} строк; "
            f"новых: {self.contracts_created} договоров, {self.organizations_created} организаций, "
            f"{self.faculty_links_created} связей с факультетами, {self.order_items_created} строк заказа"
        )


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    values: tuple
    document: ParsedDocumentNumber


@dataclass(frozen=True)
class ImportLine:
    faculty_id: int
    specialty_id: int
    qualification: str | None
    demands: dict[int, int]


@dataclass
class DocumentGroup:
    contract: Contract
    agreement: AdditionalAgreement | None
    document_date: date
    import_key: str
    rows: list[tuple[ParsedRow, ImportLine]] = dataclass_field(default_factory=list)
    raw_statuses: list[tuple[int, str]] = dataclass_field(default_factory=list)
    status: str = "Активен"
    order: Order | None = None


def text(value):
    return "" if value is None else str(value).strip()


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text(value), fmt).date()
        except ValueError:
            pass
    return None


def parse_document_number(raw_value) -> ParsedDocumentNumber:
    normalized = re.sub(r"\s+", " ", text(raw_value))
    matches = list(TOKEN_RE.finditer(normalized))
    if not matches:
        raise ValueError("не найден номер с корректной датой")
    parsed = []
    previous_end = 0
    for match in matches:
        raw_date = match.group("date")
        try:
            parsed_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
        except ValueError as error:
            raise ValueError(f"невалидная дата {raw_date}") from error
        prefix = normalized[previous_end:match.start()].strip()
        parsed.append((match.group("number"), parsed_date, bool(AGREEMENT_MARKER_RE.search(prefix))))
        previous_end = match.end()
    base_number, base_date, _ = parsed[-1]
    agreements = parsed[:-1]
    if any(not marked for _number, _date, marked in agreements):
        raise ValueError("токен перед базовым договором не помечен как дополнительное соглашение")
    if len(agreements) > 1:
        raise ValueError("в одной строке указано несколько дополнительных соглашений")
    if agreements:
        agreement_number, agreement_date, _ = agreements[0]
        return ParsedDocumentNumber(base_number, base_date, agreement_number, agreement_date)
    return ParsedDocumentNumber(base_number, base_date)


def _find_organization(session, unp, name):
    if unp:
        return session.query(Organization).filter_by(unp=unp).first(), unp
    existing = session.query(Organization).filter(func.lower(Organization.short_name) == name.lower()).first()
    if existing:
        return existing, existing.unp
    generated = f"9{int(sha256(name.casefold().encode()).hexdigest(), 16) % 100_000_000:08d}"
    if session.query(Organization.id).filter_by(unp=generated).first():
        raise ValueError(f"Неоднозначный технический УНП для «{name}».")
    return None, generated


def _document_status(group: DocumentGroup) -> str:
    normalized = []
    empty_rows = []
    for row_number, raw in group.raw_statuses:
        value = text(raw)
        if not value:
            empty_rows.append(row_number)
            normalized.append("Активен")
        else:
            normalized.append("Активен" if value.casefold() in {"активен", "active"} else "Закрыт")
    if empty_rows:
        logger.warning("Пустой статус документа %s в строках %s; принят статус Активен", group.import_key, empty_rows)
    counts = Counter(normalized or ["Активен"])
    if len(counts) > 1:
        logger.warning("Разные статусы документа %s: %s; выбран мажоритарный", group.import_key, dict(counts))
    return "Закрыт" if counts["Закрыт"] >= counts["Активен"] else "Активен"


def _sync_order(session, order: Order, desired: dict[tuple[int, int], ImportLine], qualification_present: bool):
    # Customer decision: imported current orders are editable, but a repeated
    # import is authoritative and deliberately overwrites their manual changes.
    existing = {(item.faculty_id, item.specialty_id): item for item in order.items}
    created = 0
    for key, line in desired.items():
        item = existing.pop(key, None)
        if item is None:
            item = OrderItem(order=order, faculty_id=line.faculty_id, specialty_id=line.specialty_id)
            session.add(item)
            created += 1
        if qualification_present:
            item.qualification_value = line.qualification
        demands = {row.year: row for row in item.annual_demands}
        for year, quantity in line.demands.items():
            demand = demands.get(year)
            if demand is None:
                item.annual_demands.append(AnnualDemand(year=year, quantity=quantity))
            else:
                demand.quantity = quantity
    for item in existing.values():
        session.delete(item)
    session.flush()
    return created


@audited
def import_xlsx(session, path: Path, user_id=None, original_filename=None) -> ImportResult:
    """Synchronize import-owned snapshots without touching manual revisions."""
    worksheet = load_workbook(path, data_only=True, read_only=True).active
    headers = [text(cell.value) for cell in worksheet[1]]
    index = {header: i for i, header in enumerate(headers)}
    required = {"Организация-заказчик", "Факультет", "Номер договора", "Код специальности, направления специальности, специализации"}
    missing = sorted(required - index.keys())
    if missing:
        raise ValueError(f"В Excel отсутствуют столбцы: {', '.join(missing)}")

    def field(row, label):
        return row[index[label]] if label in index else None

    def has_field(label):
        # Missing optional columns preserve stored values by confirmed business rule.
        return label in index

    years = [(int(header), i) for i, header in enumerate(headers) if header.isdigit() and 2000 <= int(header) <= 2100]
    parsed_rows = []
    for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if not text(field(row, "Организация-заказчик")):
            continue
        raw_number = field(row, "Номер договора")
        try:
            document = parse_document_number(raw_number)
        except ValueError as error:
            logger.warning("Строка %s пропущена: %s; исходное значение: %r", row_number, error, raw_number)
            continue
        parsed_rows.append(ParsedRow(row_number, tuple(row), document))

    groups: dict[tuple[int, str, int | None], DocumentGroup] = {}
    seen_organizations, seen_contracts, seen_faculties, seen_specialties = set(), set(), set(), set()
    organizations_created = contracts_created = faculty_links_created = order_items_created = 0

    for parsed in parsed_rows:
        row = parsed.values
        name = text(field(row, "Организация-заказчик"))
        organization, unp = _find_organization(session, text(field(row, "УНП")), name)
        if organization is None:
            organization = Organization(
                unp=unp, short_name=name, full_name=text(field(row, "Полное наименование")) or name,
                legal_address=text(field(row, "Адрес юридический")) or None,
                authority=text(field(row, "Ведомство")) or None, phone=text(field(row, "Телефоны")) or None,
            )
            session.add(organization)
            session.flush()
            organizations_created += 1
        else:
            organization.short_name = name
            if has_field("Полное наименование"):
                organization.full_name = text(field(row, "Полное наименование")) or name
            if has_field("Адрес юридический"):
                organization.legal_address = text(field(row, "Адрес юридический")) or None
            if has_field("Ведомство"):
                organization.authority = text(field(row, "Ведомство")) or None
            if has_field("Телефоны"):
                organization.phone = text(field(row, "Телефоны")) or None
        seen_organizations.add(organization.id)

        contract = session.query(Contract).filter_by(organization_id=organization.id, number=parsed.document.base_number).first()
        if contract is None:
            contract = Contract(
                organization_id=organization.id, number=parsed.document.base_number, status="Активен",
                start_date=parsed.document.base_date, end_date=parse_date(field(row, "Дата окончания договора")),
            )
            session.add(contract)
            session.flush()
            contracts_created += 1
        elif has_field("Дата окончания договора"):
            contract.end_date = parse_date(field(row, "Дата окончания договора"))
        seen_contracts.add(contract.id)

        faculty_name = text(field(row, "Факультет"))
        if not faculty_name:
            logger.warning("Строка %s пропущена: не указан факультет", parsed.row_number)
            continue
        faculty = get_or_create_faculty(session, faculty_name)
        seen_faculties.add(faculty.name)
        if not session.get(ContractFaculty, (contract.id, faculty.id)):
            session.add(ContractFaculty(contract_id=contract.id, faculty_id=faculty.id))
            session.flush()
            faculty_links_created += 1

        agreement = None
        if parsed.document.agreement_number:
            agreement = session.query(AdditionalAgreement).filter_by(
                contract_id=contract.id, number=parsed.document.agreement_number,
            ).first()
            if agreement is None:
                agreement = AdditionalAgreement(
                    contract_id=contract.id, number=parsed.document.agreement_number,
                    date=parsed.document.agreement_date, status="Активен",
                )
                session.add(agreement)
                session.flush()
        import_key = f"additional_agreement:{agreement.id}" if agreement else f"contract:{contract.id}"
        group_key = (contract.id, "agreement" if agreement else "contract", agreement.id if agreement else None)
        group = groups.setdefault(group_key, DocumentGroup(
            contract, agreement, parsed.document.agreement_date or parsed.document.base_date, import_key,
        ))
        group.raw_statuses.append((parsed.row_number, text(field(row, "Статус"))))

        specialty_code = text(field(row, "Код специальности, направления специальности, специализации"))
        if not specialty_code:
            continue
        qualification = text(field(row, "Квалификация")) if has_field("Квалификация") else ""
        specialty = get_or_create_specialty(session, specialty_code, qualification, faculty.name)
        seen_specialties.add(specialty.code)
        demands = {}
        for year, column in years:
            try:
                demands[year] = int(row[column] or 0)
            except (ValueError, TypeError) as error:
                raise ValueError(f"Строка {parsed.row_number}, год {year}: неверная потребность.") from error
        group.rows.append((parsed, ImportLine(faculty.id, specialty.id, qualification or None, demands)))

    by_contract: dict[int, list[DocumentGroup]] = {}
    for group in groups.values():
        group.status = _document_status(group)
        by_contract.setdefault(group.contract.id, []).append(group)

    for contract_id, contract_groups in by_contract.items():
        contract = contract_groups[0].contract
        manual_current = session.query(Order).filter_by(contract_id=contract_id, is_current=True, import_key=None).first()
        direct_group = next((group for group in contract_groups if group.agreement is None), None)
        for group in contract_groups:
            manual_document_order = None
            if group.agreement:
                manual_document_order = session.query(Order).filter_by(
                    additional_agreement_id=group.agreement.id, import_key=None,
                ).first()
            if not manual_current and not manual_document_order:
                if group.agreement:
                    group.agreement.status = group.status
                else:
                    contract.status = group.status
            group.order = session.query(Order).filter_by(import_key=group.import_key).first()
            if group.order is None:
                group.order = Order(
                    organization_id=contract.organization_id, contract_id=contract.id,
                    additional_agreement_id=group.agreement.id if group.agreement else None,
                    import_key=group.import_key, created_by=user_id, is_current=False,
                )
                session.add(group.order)
                session.flush()
            group.order.is_current = False
            group.order.status = "REPLACED"

        ordered = sorted(contract_groups, key=lambda group: (group.document_date, group.agreement is not None, group.import_key))
        active_values: dict[tuple[int, int], ImportLine] = {}
        previous_order = None
        latest_active = None
        for revision, group in enumerate(ordered, start=1):
            own_values = {(line.faculty_id, line.specialty_id): line for _row, line in group.rows}
            if group.status == "Активен":
                active_values.update(own_values)
                desired = dict(active_values)
                latest_active = group
            else:
                desired = own_values
            group.order.revision = revision
            group.order.previous_order_id = previous_order.id if previous_order else None
            order_items_created += _sync_order(session, group.order, desired, has_field("Квалификация"))
            previous_order = group.order

        if not direct_group and any(group.agreement and group.status == "Активен" for group in ordered) and not manual_current:
            contract.status = "Закрыт"
        if manual_current is None and latest_active is not None:
            latest_active.order.is_current = True
            latest_active.order.status = "CURRENT"

    session.flush()
    display_name = original_filename or path.name
    result = ImportResult(
        len(parsed_rows), len(seen_organizations), len(seen_contracts), len(seen_faculties), len(seen_specialties),
        organizations_created, contracts_created, faculty_links_created, order_items_created,
    )
    current_audit_batch(session).record_values(
        AuditAction.FILE_UPLOAD, "excel_import", None, f"Импорт Excel {display_name}",
        new={
            "filename": display_name, "rows_processed": result.rows_processed,
            "organizations": result.organizations, "contracts_created": result.contracts_created,
            "order_items_created": result.order_items_created,
            "faculty_links_created": result.faculty_links_created,
        },
    )
    return result
