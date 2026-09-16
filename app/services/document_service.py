import json

from docxtpl import DocxTemplate


def render_agreement(contract, out_path):
    """Generate an additional-agreement DOCX from the effective order."""
    items = []
    years = set()
    for item in contract.items:
        demand = json.loads(item.demand_json)
        years.update(demand)
        items.append({"specialty": item.specialty, "qualification": item.qualification, "demand": demand})
    doc = DocxTemplate("templates/dop_soglashenie.docx")
    doc.render({
        "org_name": contract.organization.name,
        "org_address": contract.organization.address or "________________",
        "contract_number": contract.number or "________________",
        "contract_date": contract.start_date.strftime("%d.%m.%Y") if contract.start_date else "________________",
        "faculty": ", ".join(contract.faculty_names),
        "years": sorted(years),
        "items": items,
    })
    doc.save(out_path)
