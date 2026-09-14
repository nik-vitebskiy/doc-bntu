import json, os, shutil, uuid
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from .models import Base, engine, SessionLocal, Organization, Contract, OrderItem, Upload
from .importer import import_xlsx
from .generator import render_agreement
from .template_builder import make_template

Path("data").mkdir(exist_ok=True); Path("uploads").mkdir(exist_ok=True)
Base.metadata.create_all(engine); make_template()
app = FastAPI(title="Кадровый заказ")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
views = Jinja2Templates(directory="app/views")
views.env.filters["fromjson"] = json.loads

def db(): return SessionLocal()
def urgency(end):
    if not end: return "neutral"
    days = (end - date.today()).days
    return "danger" if days <= 30 else "warning" if days <= 90 else "success"
views.env.globals["urgency"] = urgency

@app.get("/", response_class=HTMLResponse)
def registry(request: Request, q: str = "", faculty: str = ""):
    s = db()
    query = s.query(Contract).join(Organization)
    if q: query = query.filter(or_(Organization.name.ilike(f"%{q}%"), Contract.number.ilike(f"%{q}%")))
    if faculty: query = query.filter(Contract.faculty == faculty)
    contracts = query.order_by(Organization.name).all()
    faculties = [x[0] for x in s.query(Contract.faculty).distinct().order_by(Contract.faculty) if x[0]]
    counts = dict(s.query(Contract.faculty, __import__('sqlalchemy').func.count(Contract.id)).group_by(Contract.faculty).all())
    return views.TemplateResponse(request, "registry.html", {"contracts": contracts, "faculties": faculties, "counts": counts, "q": q, "selected_faculty": faculty})

@app.post("/import")
async def upload_import(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"): raise HTTPException(400, "Нужен файл Excel .xlsx")
    path = Path("uploads") / f"import-{uuid.uuid4()}.xlsx"
    with path.open("wb") as out: shutil.copyfileobj(file.file, out)
    s = db(); import_xlsx(path, s); s.close()
    return RedirectResponse("/", status_code=303)

@app.get("/organizations/new", response_class=HTMLResponse)
def new_org(request: Request): return views.TemplateResponse(request, "organization_form.html", {})

@app.post("/organizations/new")
def create_org(name: str = Form(...), full_name: str = Form(""), address: str = Form(""), department: str = Form(""), contact: str = Form("")):
    s = db(); org = Organization(name=name, full_name=full_name, address=address, department=department, contact=contact); s.add(org); s.commit()
    return RedirectResponse(f"/organizations/{org.id}", status_code=303)

@app.get("/organizations/{org_id}", response_class=HTMLResponse)
def organization(request: Request, org_id: int):
    s = db(); org = s.get(Organization, org_id)
    if not org: raise HTTPException(404)
    years = sorted({year for c in org.contracts for i in c.items for year in json.loads(i.demand_json).keys()})
    return views.TemplateResponse(request, "organization.html", {"org": org, "years": years})

@app.post("/organizations/{org_id}/contract")
def add_contract(org_id: int, faculty: str = Form(...), number: str = Form(""), end_date: str = Form("")):
    s = db(); c = Contract(organization_id=org_id, faculty=faculty, number=number, end_date=date.fromisoformat(end_date) if end_date else None); s.add(c); s.commit()
    return RedirectResponse(f"/organizations/{org_id}", status_code=303)

@app.post("/contracts/{contract_id}/items")
async def add_item(contract_id: int, request: Request, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    form = await request.form()
    values = {key.removeprefix("demand_"): int(value) if str(value).strip().isdigit() else 0 for key, value in form.items() if key.startswith("demand_")}
    s.add(OrderItem(contract_id=contract_id, specialty=specialty, qualification=qualification, demand_json=json.dumps(values, ensure_ascii=False))); s.commit()
    return RedirectResponse(f"/organizations/{c.organization_id}", status_code=303)

@app.post("/items/{item_id}")
async def edit_item(item_id: int, request: Request, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); item = s.get(OrderItem, item_id)
    if not item: raise HTTPException(404)
    form = await request.form()
    item.specialty, item.qualification = specialty, qualification
    item.demand_json = json.dumps({key.removeprefix("demand_"): int(value) if str(value).strip().isdigit() else 0 for key, value in form.items() if key.startswith("demand_")}, ensure_ascii=False)
    s.commit()
    return RedirectResponse(f"/organizations/{item.contract.organization_id}", status_code=303)

@app.post("/contracts/{contract_id}/scan")
async def add_scan(contract_id: int, file: UploadFile = File(...)):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    safe = Path(file.filename).name; stored = f"{uuid.uuid4()}-{safe}"
    with open(Path("uploads") / stored, "wb") as out: shutil.copyfileobj(file.file, out)
    s.add(Upload(contract_id=contract_id, filename=safe, stored_name=stored)); s.commit()
    return RedirectResponse(f"/organizations/{c.organization_id}", status_code=303)

@app.get("/contracts/{contract_id}/agreement")
def agreement(contract_id: int):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    target = Path("uploads") / f"Дополнительное_соглашение_{contract_id}.docx"; render_agreement(c, target)
    return FileResponse(target, filename=target.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
