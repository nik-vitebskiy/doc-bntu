"""Creates a compact DOCX docxtpl template from standard-library XML only."""
from pathlib import Path
def make_template(path="templates/dop_soglashenie.docx"):
    path = Path(path)
    if path.exists(): return
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.shared import Pt
    path.parent.mkdir(exist_ok=True)
    doc = Document()
    section = doc.sections[0]; section.left_margin = section.right_margin = Pt(36)
    for value, bold in [("ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ", True), ("к договору № {{ contract_number }} от {{ contract_date }}", True), ("г. Минск", False), ("Белорусский национальный технический университет и {{ org_name }}, адрес: {{ org_address }}, заключили настоящее дополнительное соглашение.", False), ("Приложение: заказ на подготовку кадров ({{ faculty }} факультет).", True)]:
        paragraph = doc.add_paragraph(); paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if bold else WD_ALIGN_PARAGRAPH.JUSTIFY; run = paragraph.add_run(value); run.bold = bold; run.font.size = Pt(10)
    years = list(range(2026, 2037)); table = doc.add_table(rows=3, cols=2 + len(years)); table.style = "Table Grid"; table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, value in zip(table.rows[0].cells, ["Код специальности", "Квалификация", *map(str, years)]): c.text = value
    table.rows[1].cells[0].text = "{%tr for row in items %}"
    for c in table.rows[1].cells[1:]: c.text = ""
    for c, value in zip(table.rows[2].cells, ["{{ row.specialty }}", "{{ row.qualification }}", *["{{ row.demand['" + str(y) + "'] }}" for y in years]]): c.text = value; c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    end = table.add_row(); end.cells[0].text = "{%tr endfor %}"
    for c in end.cells[1:]: c.text = ""
    doc.add_paragraph("БНТУ ____________________     Организация-заказчик ____________________")
    doc.save(path)
