import json
from io import BytesIO
from datetime import date
from pathlib import Path

from docxtpl import DocxTemplate

from ..template_builder import make_template


APPLICATION_TEMPLATE_PATH = Path("templates/zayavka.docx")


def application_template_ready() -> bool:
    """Return whether the customer-approved application template is available.

    Rendering is deliberately not exposed until that template is supplied: the
    application form is a regulated document and must not be guessed.
    """
    return APPLICATION_TEMPLATE_PATH.is_file()


EMPTY_REQUISITE = "___"


def _document_requisites(values: dict | None) -> dict[str, str]:
    result = {}
    for key in (
        "full_name", "signer_position", "signer_name",
        "power_of_attorney_number", "power_of_attorney_date",
        "legal_address", "unp", "okpo", "bank_account", "bank_name", "bic",
    ):
        value = (values or {}).get(key)
        if key == "power_of_attorney_date" and value:
            try:
                value = date.fromisoformat(str(value)).strftime("%d.%m.%Y")
            except ValueError:
                pass
        result[key] = str(value).strip() if value and str(value).strip() else EMPTY_REQUISITE
    return result


def render_agreement_bytes(contract, requisites: dict | None = None) -> bytes:
    """Generate an additional-agreement snapshot suitable for DB storage."""
    make_template()
    items = []
    years = set()
    for item in contract.items:
        demand = json.loads(item.demand_json)
        years.update(demand)
        items.append({"specialty": item.specialty, "qualification": item.qualification, "demand": demand})
    doc = DocxTemplate("templates/dop_soglashenie.docx")
    doc.render({
        "bntu": _document_requisites(requisites),
        "org_name": contract.organization.name,
        "org_address": contract.organization.address or "________________",
        "contract_number": contract.number or "________________",
        "contract_date": contract.start_date.strftime("%d.%m.%Y") if contract.start_date else "________________",
        "faculty": ", ".join(contract.faculty_names),
        "years": sorted(years),
        "items": items,
    })
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def render_agreement(contract, out_path, requisites: dict | None = None):
    """Compatibility wrapper used by exports and existing tests."""
    Path(out_path).write_bytes(render_agreement_bytes(contract, requisites))
