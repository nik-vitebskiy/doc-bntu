import json
from pathlib import Path
from docxtpl import DocxTemplate

def render_agreement(contract, out_path):
    org = contract.organization
    items = []
    years = set()
    for item in contract.items:
        demand = json.loads(item.demand_json)
        years.update(demand)
        items.append({"specialty": item.specialty, "qualification": item.qualification, "demand": demand})
    years = sorted(years)
    doc = DocxTemplate("templates/dop_soglashenie.docx")
    doc.render({"org_name": org.name, "org_address": org.address or "________________", "contract_number": contract.number or "________________", "contract_date": contract.start_date.strftime("%d.%m.%Y") if contract.start_date else "________________", "faculty": contract.faculty, "years": years, "items": items})
    doc.save(out_path)
