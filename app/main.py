import json, os, shutil, uuid
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .models import SessionLocal, Organization, Contract, OrderItem, AppUser
from .services.import_service import import_xlsx
from .services.document_service import render_agreement
from .services.organization_service import attach_scan, create_contract, create_organization, register_additional_agreement, registry as get_registry, save_item
from .services.auth_service import authenticate, ensure_admin, ensure_head, write_audit
from .template_builder import make_template

Path("data").mkdir(exist_ok=True); Path("uploads").mkdir(exist_ok=True)
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

@app.on_event("startup")
def startup():
    make_template()
    s = db(); ensure_admin(s); ensure_head(s); s.close()

@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.url.path.startswith(("/static", "/login")):
        return await call_next(request)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    s = db(); user = s.get(AppUser, user_id); s.close()
    if not user or not user.is_active:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    request.state.user = user
    return await call_next(request)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "change-me-before-production"), https_only=False)

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return views.TemplateResponse(request, "login.html", {"error": ""})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    s = db(); user = authenticate(s, username, password)
    if not user:
        s.close()
        return views.TemplateResponse(request, "login.html", {"error": "Неверный логин или пароль."}, status_code=401)
    write_audit(s, user.id, "LOGIN", "app_user", user.id)
    request.session["user_id"] = user.id
    s.close()
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/", response_class=HTMLResponse)
def registry(request: Request, q: str = "", faculty: str = "", end_year: str = ""):
    s = db()
    contracts, faculties, counts, end_years = get_registry(s, q, faculty, end_year)
    return views.TemplateResponse(request, "registry.html", {"contracts": contracts, "faculties": faculties, "counts": counts, "q": q, "selected_faculty": faculty, "end_years": end_years, "selected_end_year": end_year})

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
def create_org(request: Request, name: str = Form(...), full_name: str = Form(""), address: str = Form(""), department: str = Form("")):
    s = db(); org = create_organization(s, name=name, full_name=full_name, address=address, department=department); write_audit(s, request.state.user.id, "CREATE", "organization", org.id, name)
    return RedirectResponse(f"/organizations/{org.id}", status_code=303)

@app.get("/organizations/{org_id}", response_class=HTMLResponse)
def organization(request: Request, org_id: int):
    s = db(); org = s.get(Organization, org_id)
    if not org: raise HTTPException(404)
    years = sorted({year for c in org.contracts for i in c.items for year in json.loads(i.demand_json).keys()})
    return views.TemplateResponse(request, "organization.html", {"org": org, "years": years})

@app.post("/organizations/{org_id}/contract")
def add_contract(org_id: int, faculty: str = Form(...), number: str = Form(""), end_date: str = Form("")):
    s = db(); create_contract(s, org_id, faculty, number, end_date)
    return RedirectResponse(f"/organizations/{org_id}", status_code=303)

@app.post("/contracts/{contract_id}/additional-agreements")
def add_additional_agreement(request: Request, contract_id: int, number: str = Form(...), agreement_date: str = Form(...)):
    s = db(); contract = s.get(Contract, contract_id)
    if not contract: raise HTTPException(404)
    agreement = register_additional_agreement(s, contract, number, date.fromisoformat(agreement_date), request.state.user.id)
    write_audit(s, request.state.user.id, "ACTIVATE", "additional_agreement", agreement.id, f"{agreement.number}; contract={contract.id}")
    return RedirectResponse(f"/organizations/{contract.organization_id}", status_code=303)

@app.post("/contracts/{contract_id}/items")
async def add_item(contract_id: int, request: Request, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    form = await request.form()
    save_item(s, contract_id, specialty, qualification, form)
    return RedirectResponse(f"/organizations/{c.organization_id}", status_code=303)

@app.post("/items/{item_id}")
async def edit_item(item_id: int, request: Request, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); item = s.get(OrderItem, item_id)
    if not item: raise HTTPException(404)
    form = await request.form()
    save_item(s, item.contract_id, specialty, qualification, form, item)
    return RedirectResponse(f"/organizations/{item.contract.organization_id}", status_code=303)

@app.post("/contracts/{contract_id}/scan")
async def add_scan(contract_id: int, file: UploadFile = File(...)):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    safe = Path(file.filename).name; stored = f"{uuid.uuid4()}-{safe}"
    with open(Path("uploads") / stored, "wb") as out: shutil.copyfileobj(file.file, out)
    attach_scan(s, c, safe, stored)
    return RedirectResponse(f"/organizations/{c.organization_id}", status_code=303)

@app.get("/contracts/{contract_id}/agreement")
def agreement(contract_id: int):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    target = Path("uploads") / f"Дополнительное_соглашение_{contract_id}.docx"; render_agreement(c, target)
    return FileResponse(target, filename=target.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
